from __future__ import annotations

from dataclasses import dataclass, field

from src.compose.response import compose_response
from src.eligibility.engine import calculate_eligibility
from src.extraction.extract import extract_facts
from src.extraction.schema import ExtractionResult
from src.json_types import JsonObject, JsonValue
from src.planner.missing import determine_missing_fields
from src.retrieval.kb import Citation, get_by_id, retrieve, retrieve_supporting_policy
from src.safety.checks import SafetyAction, check_safety
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

    1. Safety
    2. Extract facts (LLM)
    3. Validate / update state
    4. Plan missing fields
    5. Assess if ready
    6. Retrieve policy
    7. Compose response
    """
    case = case.model_copy(deep=True)
    case.turn_count += 1
    safety = check_safety(message)

    if safety.action == SafetyAction.CRISIS:
        return TurnResult(
            reply=safety.user_message or "",
            case=case,
            safety_action=safety.action.value,
            debug={"stopped": "crisis"},
        )

    if safety.action == SafetyAction.REFUSE_SCOPE:
        return TurnResult(
            reply=safety.user_message or "",
            case=case,
            safety_action=safety.action.value,
            debug={"stopped": "scope"},
        )

    # Application refuse: respond but allow pure application asks to stop;
    # if message is only an application request, stop; if mixed, still continue.
    safety_preamble = None
    working_message = safety.redacted_message or message

    if safety.action == SafetyAction.REFUSE_APPLICATION:
        # If the message is primarily an application request, stop this turn
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
            return TurnResult(
                reply=safety.user_message or "",
                case=case,
                safety_action=safety.action.value,
                debug={"stopped": "application"},
            )
        safety_preamble = safety.user_message

    if safety.action in (SafetyAction.PII_WARN, SafetyAction.INJECTION_NOTICE):
        safety_preamble = safety.user_message
        case.pii_warned = case.pii_warned or safety.action == SafetyAction.PII_WARN
        working_message = safety.redacted_message or message

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

    assessment: Assessment | None = None
    citations: list[Citation] = []
    policy_context = None

    # Policy question handling (even mid-intake)
    intents = extraction.get("user_intents") or []
    if "policy_question" in intents or extraction.get("policy_question"):
        q = extraction.get("policy_question") or working_message
        citations = retrieve(q, limit=2)
        if citations:
            doc = get_by_id(citations[0].source_id)
            policy_context = (
                f"Regarding your question, here is relevant public policy context "
                f"from **{citations[0].title}**:\n\n"
                f"{(doc.text if doc else citations[0].snippet)[:900]}"
            )

    if plan.ready_to_assess:
        assessment = calculate_eligibility(case)
        case.assessment = assessment
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
    )

    debug: JsonObject = {
        "extraction": _extraction_json(extraction),
        "missing": list(plan.missing_fields),
        "stage": case.stage.value,
    }

    return TurnResult(
        reply=reply,
        case=case,
        safety_action=safety.action.value,
        assessment=assessment,
        citations=citations,
        debug=debug,
    )


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
