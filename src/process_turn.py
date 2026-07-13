from __future__ import annotations

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
from src.planner.missing import determine_missing_fields
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
        return TurnResult(
            reply=MESSAGE_TOO_LONG_REPLY,
            case=case,
            safety_action="message_too_long",
            debug=_debug(
                case,
                stopped="message_too_long",
                message_chars=len(message),
                max_message_chars=max_chars,
            ),
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
            return TurnResult(
                reply=reply,
                case=case,
                safety_action=safety_fb.action.value,
                debug=_debug(case, stopped="crisis", safety_source=safety_fb.source),
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
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=_debug(case, stopped="crisis", safety_source=safety.source),
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
            return TurnResult(
                reply=reply,
                case=case,
                safety_action=safety.action.value,
                debug=_debug(
                    case,
                    stopped="application",
                    safety_source=safety.source,
                ),
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
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=_debug(
                case,
                steered=safety.action.value,
                safety_source=safety.source,
                missing=list(plan.missing_fields),
                extraction=_extraction_json(extraction),
            ),
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

    return TurnResult(
        reply=reply,
        case=case,
        safety_action=safety.action.value,
        assessment=assessment,
        citations=citations,
        debug=_debug(
            case,
            extraction=_extraction_json(extraction),
            missing=list(plan.missing_fields),
            safety_source=safety.source,
        ),
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
        "lives_in_nc",
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
    extra: JsonObject = {
        "stopped": "service_unavailable",
        "service_kind": exc.kind,
        "service_phase": phase,
    }
    if extraction is not None:
        extra["extraction"] = _extraction_json(extraction)
    if missing is not None:
        extra["missing"] = list(missing)
    return TurnResult(
        reply=reply,
        case=case,
        safety_action="service_unavailable",
        assessment=assessment,
        citations=citations or [],
        debug=_debug(case, **extra),
    )


def _debug(case: EligibilityCase, **extra: JsonValue) -> JsonObject:
    out: JsonObject = {
        "stage": case.stage.value,
        "turn_count": case.turn_count,
        "history_turns": len(case.recent_turns),
        "disclaimer_given": case.disclaimer_given,
    }
    if case.assessment is not None:
        out["assessment_status"] = case.assessment.status.value
    for key, val in extra.items():
        out[key] = val
    return out


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
