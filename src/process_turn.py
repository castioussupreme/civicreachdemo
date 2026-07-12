from __future__ import annotations

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
from src.planner.missing import determine_missing_fields
from src.retrieval.kb import Citation, get_by_id, retrieve, retrieve_supporting_policy
from src.safety.checks import SafetyAction, check_safety, redact_pii
from src.state.models import Assessment, EligibilityCase, Stage
from src.state.updates import apply_validated_updates


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

    0. Message length (same limit as transcript retention)
    1. Safety (and PII redaction for storage/extract)
    2. Extract facts (LLM)
    3. Validate / update state
    4. Plan missing fields
    5. Assess if ready
    6. Retrieve policy
    7. Compose response (history for wording only)

    User transcript entries are always PII-redacted before append.
    Oversized user messages are not stored and get a friendly summarize prompt.
    """
    case = case.model_copy(deep=True)
    case.turn_count += 1
    max_chars = get_settings().max_message_chars

    if len(message) > max_chars:
        # Do not retain the wall of text (PII risk + prompt blow-up).
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

    safety = check_safety(message)

    # Never store raw SSN/address in Redis/history — even on crisis/scope early exits.
    history_user, _ = redact_pii(message)
    if safety.redacted_message is not None:
        history_user = safety.redacted_message
    case.append_turn("user", history_user, max_chars=max_chars)

    if safety.action == SafetyAction.CRISIS:
        reply = safety.user_message or ""
        case.append_turn("assistant", reply, max_chars=max_chars)
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=_debug(case, stopped="crisis"),
        )

    if safety.action == SafetyAction.REFUSE_SCOPE:
        reply = safety.user_message or ""
        case.append_turn("assistant", reply, max_chars=max_chars)
        return TurnResult(
            reply=reply,
            case=case,
            safety_action=safety.action.value,
            debug=_debug(case, stopped="scope"),
        )

    safety_preamble = None
    working_message = (
        safety.redacted_message if safety.redacted_message is not None else history_user
    )

    if safety.action == SafetyAction.REFUSE_APPLICATION:
        lower = message.lower()
        has_eligibility_content = any(
            k in lower
            for k in (
                "income",
                "household",
                "make",
                "earn",
                "live in",
                "people",
                "eligible",
            )
        )
        if not has_eligibility_content:
            reply = safety.user_message or ""
            case.append_turn("assistant", reply, max_chars=max_chars)
            return TurnResult(
                reply=reply,
                case=case,
                safety_action=safety.action.value,
                debug=_debug(case, stopped="application"),
            )
        safety_preamble = safety.user_message

    if safety.action in (SafetyAction.PII_WARN, SafetyAction.INJECTION_NOTICE):
        safety_preamble = safety.user_message
        case.pii_warned = case.pii_warned or safety.action == SafetyAction.PII_WARN
        working_message = safety.redacted_message or history_user

    extraction: ExtractionResult = extract_facts(
        working_message,
        case,
        previous_question=case.last_question,
    )
    case = apply_validated_updates(case, extraction, turn=case.turn_count)

    plan = determine_missing_fields(case)
    case.stage = plan.stage
    case.last_missing_fields = plan.missing_fields
    if plan.next_question_hint:
        case.last_question = plan.next_question_hint
    # Remember one-shot follow-ups so we do not loop forever
    if "approx_gross" in plan.missing_fields:
        case.asked_for_gross_amount = True
    if "approx_household_total" in plan.missing_fields:
        case.asked_for_household_total = True

    assessment: Assessment | None = None
    citations: list[Citation] = []
    policy_context = None

    intents = extraction.get("user_intents") or []
    if "policy_question" in intents or extraction.get("policy_question"):
        q = extraction.get("policy_question") or working_message
        citations = retrieve(q, limit=2)
        if citations:
            doc = get_by_id(citations[0].source_id)
            # Plain context for compose — no markdown report framing
            policy_context = (
                f"From public source “{citations[0].title}”: "
                f"{(doc.text if doc else citations[0].snippet)[:700]}"
            )

    if plan.ready_to_assess:
        assessment = calculate_eligibility(case)
        case.assessment = assessment
        if is_terminal_assessment(assessment):
            case.stage = Stage.ASSESSED
        citations = retrieve_supporting_policy(
            assessment.source_ids,
            user_query=working_message,
            limit=3,
        )

    reply = compose_response(
        case=case,
        plan=plan,
        assessment=assessment,
        citations=citations,
        safety_preamble=safety_preamble,
        policy_answer_context=policy_context,
        user_message=working_message,
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
        ),
    )


def _debug(case: EligibilityCase, **extra: JsonValue) -> JsonObject:
    """Structured turn metadata for ?debug= / CLI /debug — not shown in normal replies."""
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
    """Serialize ExtractionResult for debug without Any."""
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
    return out
