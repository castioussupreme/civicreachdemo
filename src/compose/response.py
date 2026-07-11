from __future__ import annotations

import json

from src.eligibility.ruleset import RULESET
from src.llm.client import chat_text
from src.planner.missing import PlanResult
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus, EligibilityCase

DISCLAIMER = (
    "This is an informal likelihood screen only—not an official determination. "
    "Your county Department of Social Services (DSS) decides eligibility."
)

STATUS_LABELS = {
    AssessmentStatus.LIKELY_ELIGIBLE: "Likely eligible (screening)",
    AssessmentStatus.LIKELY_INELIGIBLE: "Likely not eligible (screening)",
    AssessmentStatus.NEEDS_MORE_INFORMATION: "Need more information",
    AssessmentStatus.UNABLE_TO_DETERMINE: "Unable to determine with confidence",
}


def compose_response(
    *,
    case: EligibilityCase,
    plan: PlanResult,
    assessment: Assessment | None,
    citations: list[Citation],
    safety_preamble: str | None = None,
    policy_answer_context: str | None = None,
) -> str:
    system = (
        "You are a careful NC FNS (SNAP) eligibility screening assistant. "
        "Be warm, clear, and concise. Never invent thresholds or rules. "
        "Only use the structured assessment, plan, and citation snippets provided. "
        "Never claim to submit applications. Always include a brief unofficial-screening disclaimer. "
        "If asking a question, ask ONE primary question. "
        "If assessment is present, lead with the screening result label."
    )
    user = json.dumps(
        {
            "known_state": case.known_summary(),
            "plan": {
                "missing": plan.missing_fields,
                "next_question_hint": plan.next_question_hint,
                "ready": plan.ready_to_assess,
            },
            "assessment": assessment.model_dump() if assessment else None,
            "citations": [c.__dict__ for c in citations],
            "policy_context": policy_answer_context,
            "safety_preamble": safety_preamble,
            "ruleset": {
                "id": RULESET.id,
                "effective_from": RULESET.effective_from,
                "effective_to": RULESET.effective_to,
            },
            "status_labels": {k.value: v for k, v in STATUS_LABELS.items()},
        },
        default=str,
    )
    text = chat_text(system=system, user=user, temperature=0.3)
    if DISCLAIMER.lower()[:20] not in text.lower() and "informal" not in text.lower():
        text = text.rstrip() + "\n\n" + DISCLAIMER
    if safety_preamble and safety_preamble.strip() not in text:
        text = safety_preamble.strip() + "\n\n" + text
    if policy_answer_context and policy_answer_context[:80] not in text:
        text = policy_answer_context.strip() + "\n\n" + text
    return text
