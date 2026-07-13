from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.compose.response import compose_response, is_terminal_assessment
from src.config import get_settings
from src.eligibility.engine import calculate_eligibility
from src.extraction.extract import extract_facts
from src.extraction.schema import ExtractionResult
from src.json_types import JsonObject, JsonValue
from src.limits import (
    LONG_MESSAGE_HISTORY_PLACEHOLDER,
    MESSAGE_TOO_LONG_REPLY,
)
from src.openai_errors import OpenAIServiceError
from src.planner.missing import PlanResult, determine_missing_fields
from src.programs.registry import get_program
from src.retrieval.kb import Citation, get_by_id, retrieve, retrieve_supporting_policy
from src.safety.checks import (
    PII_RESPONSE,
    SafetyAction,
    personalize_safety_notice,
    redact_pii,
    resolve_safety,
)
from src.state.models import Assessment, EligibilityCase, Stage
from src.state.updates import apply_validated_updates

logger = logging.getLogger(__name__)

# Whole-message go-ahead after the scope intro (before household/income intake)
_GO_AHEAD_RE = re.compile(
    r"^\s*(?:yes|yep|yeah|yup|sure|ok|okay|continue|please|ready|start|"
    r"go\s*ahead|let'?s\s*(?:go|start|do\s*it)|sounds?\s*good|"
    r"i\s*(?:do|would|am\s*ready)|absolutely|of\s*course)"
    r"(?:\s*(?:please|thanks|thank\s*you))?[.!\s]*$",
    re.IGNORECASE,
)

_STEER_ACTIONS = frozenset(
    {
        SafetyAction.REFUSE_SCOPE,
        SafetyAction.STEER_OFF_TOPIC,
        SafetyAction.INJECTION_NOTICE,
    }
)


@dataclass
class TurnResult:
    reply: str
    case: EligibilityCase
    safety_action: str
    assessment: Assessment | None = None
    citations: list[Citation] = field(default_factory=list)
    debug: JsonObject = field(default_factory=dict)


def process_turn(message: str, case: EligibilityCase) -> TurnResult:
    """
    Fixed pipeline — code owns control flow.

    0. Message length
    1. Extract facts + safety signals (LLM)
    2. Resolve safety (LLM confidence primary, regex fallback)
    3. Validate / update state (when continuing)
    4. Plan missing fields
    5. Assess if ready
    6. Retrieve policy
    7. Compose response

    User transcript entries are PII-redacted before append when dual safety says so.
    """
    case = case.model_copy(deep=True)
    case.turn_count += 1
    max_chars = get_settings().max_message_chars
    program_label = _program_label(case.program_slug)

    if len(message) > max_chars:
        case.append_turn("user", LONG_MESSAGE_HISTORY_PLACEHOLDER, max_chars=max_chars)
        case.append_turn("assistant", MESSAGE_TOO_LONG_REPLY, max_chars=max_chars)
        debug = build_turn_debug(
            case,
            safety_action="message_too_long",
            stopped="message_too_long",
            message_chars=len(message),
            max_message_chars=max_chars,
        )
        _log_turn(debug)
        return TurnResult(
            reply=MESSAGE_TOO_LONG_REPLY,
            case=case,
            safety_action="message_too_long",
            debug=debug,
        )

    # 1) Extract first (facts + safety confidence). On LLM failure, regex-only fallback.
    extraction: ExtractionResult | None = None
    try:
        extraction = extract_facts(
            message,
            case,
            previous_question=case.last_question,
        )
    except OpenAIServiceError as exc:
        # Still try to handle crisis/PII via regex fallback before failing the turn
        safety_fb = resolve_safety(message, extraction=None)
        history_user, _ = redact_pii(message)
        if safety_fb.redacted_message is not None:
            history_user = safety_fb.redacted_message
        case.append_turn("user", history_user, max_chars=max_chars)
        if safety_fb.action == SafetyAction.CRISIS:
            reply = safety_fb.user_message or ""
            case.append_turn("assistant", reply, max_chars=max_chars)
            debug = build_turn_debug(
                case,
                safety_action=safety_fb.action.value,
                stopped="crisis",
                safety_source=safety_fb.source,
            )
            _log_turn(debug)
            return TurnResult(
                reply=reply,
                case=case,
                safety_action=safety_fb.action.value,
                debug=debug,
            )
        return _openai_failure_turn(case, max_chars=max_chars, exc=exc, phase="extract")

    # 2) Dual safety resolution
    safety = resolve_safety(message, extraction)
    history_user = message.strip()
    if safety.redacted_message is not None:
        history_user = safety.redacted_message
    else:
        # Mechanical scrub if dual said pii via either path
        scrubbed, found = redact_pii(message)
        if found:
            history_user = scrubbed
    case.append_turn("user", history_user, max_chars=max_chars)

    if safety.action == SafetyAction.CRISIS:
        reply = safety.user_message or ""
        case.append_turn("assistant", reply, max_chars=max_chars)
        debug = build_turn_debug(
            case,
            safety_action=safety.action.value,
            stopped="crisis",
            safety_source=safety.source,
            extraction=_extraction_json(extraction),
        )
        _log_turn(debug)
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=debug,
        )

    safety_preamble: str | None = None
    working_message = history_user

    if safety.action == SafetyAction.REFUSE_APPLICATION:
        if not _extraction_has_screening_facts(extraction):
            plan_early = determine_missing_fields(case)
            follow = (
                plan_early.next_question_hint
                or case.last_question
                or "If you still want a quick eligibility check, say yes when you're ready."
            )
            notice = personalize_safety_notice(safety.action, program_label=program_label) or (
                safety.user_message or ""
            )
            reply = f"{notice.rstrip()} {follow}".strip()
            case.append_turn("assistant", reply, max_chars=max_chars)
            debug = build_turn_debug(
                case,
                safety_action=safety.action.value,
                stopped="application",
                safety_source=safety.source,
                extraction=_extraction_json(extraction),
                plan=plan_early,
            )
            _log_turn(debug)
            return TurnResult(
                reply=reply,
                case=case,
                safety_action=safety.action.value,
                debug=debug,
            )
        safety_preamble = (
            personalize_safety_notice(safety.action, program_label=program_label)
            or safety.user_message
        )

    if safety.action in _STEER_ACTIONS or safety.action == SafetyAction.PII_WARN:
        if safety.action == SafetyAction.PII_WARN:
            safety_preamble = safety.user_message or PII_RESPONSE
        elif safety.action == SafetyAction.INJECTION_NOTICE and "pii" in safety.reasons:
            safety_preamble = (
                (personalize_safety_notice(safety.action, program_label=program_label) or "")
                + " "
                + PII_RESPONSE
            ).strip()
        else:
            safety_preamble = personalize_safety_notice(safety.action, program_label=program_label)
        case.pii_warned = case.pii_warned or (
            safety.action == SafetyAction.PII_WARN or "pii" in safety.reasons
        )

    # 3) Apply extracted screening facts (after safety gate)
    case = apply_validated_updates(case, extraction, turn=case.turn_count)

    # Opening already covered scope; wait for go-ahead before intake questions
    if not case.screening_started and _user_ready_to_screen(working_message, extraction):
        case.screening_started = True

    plan = determine_missing_fields(case)
    case.stage = plan.stage
    case.last_missing_fields = plan.missing_fields
    if plan.next_question_hint:
        case.last_question = plan.next_question_hint
    if "approx_gross" in plan.missing_fields:
        case.asked_for_gross_amount = True
    if "approx_household_total" in plan.missing_fields:
        case.asked_for_household_total = True

    # Pure detour: code-owned refuse + next screening question
    if safety.action in _STEER_ACTIONS and not _extraction_has_screening_facts(extraction):
        follow = (
            plan.next_question_hint
            or case.last_question
            or "When you're ready, we can start a quick eligibility check."
        )
        notice = (
            safety_preamble
            or personalize_safety_notice(safety.action, program_label=program_label)
            or f"I need to stick to {program_label}."
        ).rstrip()
        reply = f"{notice} {follow}".strip()
        case.append_turn("assistant", reply, max_chars=max_chars)
        debug = build_turn_debug(
            case,
            safety_action=safety.action.value,
            steered=safety.action.value,
            safety_source=safety.source,
            extraction=_extraction_json(extraction),
            plan=plan,
        )
        _log_turn(debug)
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=debug,
        )

    assessment: Assessment | None = None
    citations: list[Citation] = []
    policy_context = None

    program_slug = (case.program_slug or "").strip()
    if not program_slug:
        raise ValueError(
            "case.program_slug is required (create a session with an explicit program)"
        )
    as_of = case.as_of or None
    intents = extraction.get("user_intents") or []
    if "policy_question" in intents or extraction.get("policy_question"):
        q = extraction.get("policy_question") or working_message
        citations = retrieve(q, limit=2, program_slug=program_slug, as_of=as_of)
        if citations:
            doc = get_by_id(citations[0].source_id, program_slug=program_slug)
            policy_context = (
                f"From public source “{citations[0].title}”: "
                f"{(doc.text if doc else citations[0].snippet)[:700]}"
            )

    already_terminal = (
        case.stage == Stage.ASSESSED
        and case.assessment is not None
        and is_terminal_assessment(case.assessment)
    )
    post_assess = False

    if plan.ready_to_assess:
        assessment = calculate_eligibility(case)
        if (
            already_terminal
            and case.assessment is not None
            and assessment.status == case.assessment.status
            and assessment.threshold_used == case.assessment.threshold_used
            and assessment.normalized_gross_monthly == case.assessment.normalized_gross_monthly
            and assessment.household_size == case.assessment.household_size
        ):
            post_assess = True
            assessment = case.assessment
        else:
            case.assessment = assessment
            if is_terminal_assessment(assessment):
                case.stage = Stage.ASSESSED
        citations = retrieve_supporting_policy(
            assessment.source_ids,
            user_query=working_message,
            limit=3,
            program_slug=program_slug,
            as_of=as_of,
        )
    elif already_terminal:
        assessment = case.assessment
        post_assess = True

    try:
        reply = compose_response(
            case=case,
            plan=plan,
            assessment=assessment,
            citations=citations,
            safety_preamble=safety_preamble,
            policy_answer_context=policy_context,
            user_message=working_message,
            post_assess=post_assess,
        )
    except OpenAIServiceError as exc:
        return _openai_failure_turn(
            case,
            max_chars=max_chars,
            exc=exc,
            phase="compose",
            assessment=assessment,
            citations=citations,
            extraction=extraction,
            missing=list(plan.missing_fields),
        )

    case.append_turn("assistant", reply, max_chars=max_chars)

    debug = build_turn_debug(
        case,
        safety_action=safety.action.value,
        safety_source=safety.source,
        extraction=_extraction_json(extraction),
        plan=plan,
        assessment=assessment,
        citations=citations,
        post_assess=post_assess,
    )
    _log_turn(debug)
    return TurnResult(
        reply=reply,
        case=case,
        safety_action=safety.action.value,
        assessment=assessment,
        citations=citations,
        debug=debug,
    )


def _program_label(slug: str) -> str:
    try:
        return get_program(slug).display_name
    except Exception:
        return "this eligibility screen"


def _extraction_has_screening_facts(extraction: ExtractionResult) -> bool:
    facts = extraction.get("facts") or {}
    if not isinstance(facts, dict):
        return False
    keys = (
        "lives_in_service_area",
        "household_size",
        "income_amount",
        "income_period",
        "gross_or_net",
        "household_or_individual",
        "is_student",
        "elderly_or_disabled_member",
        "confirm_field",
    )
    return any(facts.get(key) is not None for key in keys)


def _user_ready_to_screen(message: str, extraction: ExtractionResult) -> bool:
    """True when the user consents or already volunteered screening facts."""
    if _extraction_has_screening_facts(extraction):
        return True
    return bool(_GO_AHEAD_RE.match(message.strip()))


def _openai_failure_turn(
    case: EligibilityCase,
    *,
    max_chars: int,
    exc: OpenAIServiceError,
    phase: str,
    assessment: Assessment | None = None,
    citations: list[Citation] | None = None,
    extraction: ExtractionResult | None = None,
    missing: list[str] | None = None,
) -> TurnResult:
    reply = exc.user_message
    case.append_turn("assistant", reply, max_chars=max_chars)
    plan_stub: PlanResult | None = None
    if missing is not None:
        plan_stub = PlanResult(
            missing_fields=list(missing),
            stage=case.stage,
            next_question_hint=case.last_question or "",
            ready_to_assess=False,
            open_contradictions=[],
        )
    debug = build_turn_debug(
        case,
        safety_action="service_unavailable",
        stopped="service_unavailable",
        service_kind=exc.kind,
        service_phase=phase,
        extraction=_extraction_json(extraction) if extraction is not None else None,
        plan=plan_stub,
        assessment=assessment,
        citations=citations,
    )
    _log_turn(debug)
    return TurnResult(
        reply=reply,
        case=case,
        safety_action="service_unavailable",
        assessment=assessment,
        citations=citations or [],
        debug=debug,
    )


def build_turn_debug(
    case: EligibilityCase,
    *,
    safety_action: str,
    safety_source: str = "",
    extraction: JsonValue | None = None,
    plan: PlanResult | None = None,
    assessment: Assessment | None = None,
    citations: list[Citation] | None = None,
    post_assess: bool = False,
    stopped: str | None = None,
    steered: str | None = None,
    message_chars: int | None = None,
    max_message_chars: int | None = None,
    service_kind: str | None = None,
    service_phase: str | None = None,
) -> JsonObject:
    """
    Structured per-turn trace for live debugging (?debug=true / CLI /debug on).

    Always available on TurnResult.debug; API only returns it when requested.
    Agent process also logs a one-line summary via _log_turn.
    """
    assess = assessment if assessment is not None else case.assessment
    missing_raw = list(plan.missing_fields) if plan is not None else list(case.last_missing_fields)
    missing_jv: list[JsonValue] = [str(m) for m in missing_raw]
    open_c: list[JsonValue] = [str(c) for c in plan.open_contradictions] if plan is not None else []
    cite_ids = [c.source_id for c in (citations or [])]
    out: JsonObject = {
        "program": {
            "slug": case.program_slug,
            "ruleset_id": case.ruleset_id,
            "as_of": case.as_of,
            "ruleset_effective_from": case.ruleset_effective_from,
            "ruleset_effective_to": case.ruleset_effective_to,
        },
        "turn": {
            "count": case.turn_count,
            "stage": case.stage.value,
            "history_turns": len(case.recent_turns),
            "screening_started": case.screening_started,
            "post_assess": post_assess,
        },
        "safety": {
            "action": safety_action,
            "source": safety_source or "none",
        },
        "plan": {
            "missing": missing_jv,
            "ready_to_assess": bool(plan.ready_to_assess) if plan is not None else False,
            "next_question_hint": (plan.next_question_hint if plan is not None else "")
            or (case.last_question or ""),
            "open_contradictions": open_c,
        },
        "known": case.known_summary(),
        "flags": {
            "scope_intro_given": case.scope_intro_given,
            "disclaimer_given": case.disclaimer_given,
            "next_steps_given": case.next_steps_given,
            "pii_warned": case.pii_warned,
            "asked_for_gross_amount": case.asked_for_gross_amount,
            "asked_for_household_total": case.asked_for_household_total,
            "period_notice_given": case.period_notice_given,
        },
    }
    if extraction is not None:
        out["extraction"] = extraction
    if assess is not None:
        reasons_jv: list[JsonValue] = [str(r) for r in assess.reasons[:5]]
        source_ids_jv: list[JsonValue] = [str(s) for s in assess.source_ids]
        out["assessment"] = {
            "status": assess.status.value,
            "threshold_used": assess.threshold_used,
            "normalized_gross_monthly": assess.normalized_gross_monthly,
            "household_size": assess.household_size,
            "source_ids": source_ids_jv,
            "reasons": reasons_jv,
        }
    if cite_ids:
        cite_list: list[JsonValue] = [
            {"source_id": c.source_id, "title": c.title} for c in (citations or [])
        ]
        out["citations"] = cite_list
    if stopped:
        out["stopped"] = stopped
    if steered:
        out["steered"] = steered
    if message_chars is not None:
        out["message_chars"] = message_chars
    if max_message_chars is not None:
        out["max_message_chars"] = max_message_chars
    if service_kind is not None:
        out["service_kind"] = service_kind
    if service_phase is not None:
        out["service_phase"] = service_phase
    return out


def _log_turn(debug: JsonObject) -> None:
    """One-line structured summary for agent Docker logs (live review)."""
    prog = debug.get("program") if isinstance(debug.get("program"), dict) else {}
    turn = debug.get("turn") if isinstance(debug.get("turn"), dict) else {}
    safety = debug.get("safety") if isinstance(debug.get("safety"), dict) else {}
    plan = debug.get("plan") if isinstance(debug.get("plan"), dict) else {}
    assess = debug.get("assessment") if isinstance(debug.get("assessment"), dict) else {}
    missing = plan.get("missing") if isinstance(plan, dict) else []
    if not isinstance(missing, list):
        missing = []
    logger.info(
        "turn program=%s ruleset=%s n=%s stage=%s safety=%s/%s missing=%s assess=%s stopped=%s",
        prog.get("slug") if isinstance(prog, dict) else "",
        prog.get("ruleset_id") if isinstance(prog, dict) else "",
        turn.get("count") if isinstance(turn, dict) else "",
        turn.get("stage") if isinstance(turn, dict) else "",
        safety.get("action") if isinstance(safety, dict) else "",
        safety.get("source") if isinstance(safety, dict) else "",
        ",".join(str(m) for m in missing[:6]) or "-",
        assess.get("status") if isinstance(assess, dict) else "-",
        debug.get("stopped") or "-",
    )


def _extraction_json(extraction: ExtractionResult) -> JsonValue:
    out: JsonObject = {}
    facts = extraction.get("facts")
    if facts is not None:
        facts_obj: JsonObject = {}
        for key, val in facts.items():
            if isinstance(val, dict):
                nested: JsonObject = {
                    str(nk): float(nv) if isinstance(nv, int | float) else str(nv)
                    for nk, nv in val.items()
                }
                facts_obj[str(key)] = nested
            elif val is None or isinstance(val, bool | int | float | str):
                facts_obj[str(key)] = val
            else:
                facts_obj[str(key)] = str(val)
        out["facts"] = facts_obj
    intents = extraction.get("user_intents")
    if intents is not None:
        out["user_intents"] = list(intents)
    if "policy_question" in extraction:
        out["policy_question"] = extraction.get("policy_question")
    if "notes" in extraction:
        out["notes"] = extraction.get("notes")
    safety = extraction.get("safety")
    if isinstance(safety, dict):
        safety_obj: JsonObject = {}
        for sk, sv in safety.items():
            if isinstance(sv, dict):
                safety_obj[str(sk)] = {
                    "flag": bool(sv.get("flag")),
                    "confidence": float(sv["confidence"])
                    if isinstance(sv.get("confidence"), int | float)
                    else 0.0,
                }
        out["safety"] = safety_obj
    return out
