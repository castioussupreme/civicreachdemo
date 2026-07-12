from __future__ import annotations

import json

from src.eligibility.ruleset import RULESET
from src.llm.client import chat_text
from src.planner.missing import PlanResult
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus, EligibilityCase

# Soft line — only appended on a terminal screening result, and at most once per case.
DISCLAIMER = (
    "Just a heads-up: this is an informal screen, not an official decision — "
    "your county DSS makes the final call."
)

# Terminal outcomes where a short disclaimer is appropriate once
_TERMINAL_STATUSES = frozenset(
    {
        AssessmentStatus.LIKELY_ELIGIBLE,
        AssessmentStatus.LIKELY_INELIGIBLE,
        AssessmentStatus.UNABLE_TO_DETERMINE,
    }
)


def is_terminal_assessment(assessment: Assessment | None) -> bool:
    return assessment is not None and assessment.status in _TERMINAL_STATUSES


def should_append_disclaimer(case: EligibilityCase, assessment: Assessment | None) -> bool:
    """Code rail: disclaimer only once, only on a real screening conclusion."""
    if case.disclaimer_given:
        return False
    return is_terminal_assessment(assessment)


def _friendly_outcome(status: AssessmentStatus) -> str:
    return {
        AssessmentStatus.LIKELY_ELIGIBLE: (
            "Based on the public income screen, they may qualify — say that in plain words."
        ),
        AssessmentStatus.LIKELY_INELIGIBLE: (
            "Based on the public income screen, they may not qualify — say that gently and clearly."
        ),
        AssessmentStatus.UNABLE_TO_DETERMINE: (
            "You cannot give a clean yes/no from this simple screen. Explain why in plain words "
            "using reasons (take-home vs before-tax, one person vs whole household, student rules, "
            "etc.). Do NOT invent tax brackets, other people's income, or student exemptions. "
            "If the gross table would have passed but student status blocks confidence, say that "
            "clearly. Suggest applying so DSS can review, or sharing the missing detail if simple."
        ),
        AssessmentStatus.NEEDS_MORE_INFORMATION: (
            "Do not announce a status. Just ask for the missing detail naturally."
        ),
    }[status]


def compose_response(
    *,
    case: EligibilityCase,
    plan: PlanResult,
    assessment: Assessment | None,
    citations: list[Citation],
    safety_preamble: str | None = None,
    policy_answer_context: str | None = None,
    user_message: str | None = None,
) -> str:
    terminal = is_terminal_assessment(assessment)
    include_disclaimer_hint = should_append_disclaimer(case, assessment)

    if assessment is not None and assessment.status == AssessmentStatus.NEEDS_MORE_INFORMATION:
        mode = "ask_follow_up"
    elif terminal:
        mode = "share_screening_result"
    elif plan.next_question_hint:
        mode = "collect_info"
    elif policy_answer_context:
        mode = "answer_policy_then_continue"
    else:
        mode = "collect_info"

    system = (
        "You are a friendly person helping someone check whether they might qualify for "
        "North Carolina FNS (food assistance / SNAP). You are not a government worker and "
        "you cannot submit applications.\n"
        "\n"
        "VOICE (critical):\n"
        "- Talk like a helpful human texting, not a form, portal, or call-center script.\n"
        "- Short messages: usually 1-3 sentences during intake; a bit more only for a final result.\n"
        "- Acknowledge what they just said in natural words, then one clear next step or question.\n"
        "- Never use robotic section headers, bullet status labels, or phrases like "
        '"Need more information", "Likely eligible (screening)", "Status:", '
        '"Assessment:", or "Unofficial determination".\n'
        "- Never list internal field names (lives_in_nc, income_period, etc.).\n"
        "- Do not repeat a full legal disclaimer every turn. "
        + (
            "On this turn only, end with one short plain-language note that this is informal "
            "and DSS decides.\n"
            if include_disclaimer_hint
            else "Skip disclaimers on this turn — it was already covered or not needed yet.\n"
        )
        + "\n"
        "FACTS (critical):\n"
        "- known_facts is the source of truth. conversation_history is only for wording and continuity.\n"
        "- If history and known_facts disagree, trust known_facts.\n"
        "- Never invent dollar thresholds or rules. Use numbers only from screening_result or citations.\n"
        "- Never claim you filed an application or contacted DSS.\n"
        "\n"
        "THIS TURN mode="
        + mode
        + ":\n"
        + (
            "- Share the screening outcome in plain language using outcome_guidance.\n"
            "- Mention the monthly income figure and public threshold if provided.\n"
            "- Optionally one short citation-backed note; keep it light.\n"
            if mode == "share_screening_result"
            else "- Ask exactly ONE natural question (use next_question_hint as the idea, rephrase freely).\n"
            "- Do not recap every known fact. Do not say you still need more information as a status.\n"
            if mode == "collect_info" or mode == "ask_follow_up"
            else "- Answer using policy_context only, briefly, then continue intake if needed.\n"
        )
    )

    history = [{"role": t.role, "text": t.text} for t in case.recent_turns]

    screening_payload: dict[str, object] | None = None
    if assessment is not None and terminal:
        screening_payload = {
            "outcome_guidance": _friendly_outcome(assessment.status),
            "monthly_income": assessment.normalized_gross_monthly,
            "threshold": assessment.threshold_used,
            "household_size": assessment.household_size,
            "reasons": list(assessment.reasons),
            # Caveats without the boilerplate "informal screening" line (we handle that separately)
            "extra_notes": [
                c
                for c in assessment.caveats
                if "informal screening" not in c.lower() and "not an official" not in c.lower()
            ][:4],
        }
    elif assessment is not None and assessment.status == AssessmentStatus.NEEDS_MORE_INFORMATION:
        screening_payload = {
            "outcome_guidance": _friendly_outcome(assessment.status),
            "reasons": list(assessment.reasons),
        }

    user = json.dumps(
        {
            "mode": mode,
            "user_just_said": user_message,
            "conversation_history": history,
            "known_facts": case.known_summary(),
            "next_question_hint": plan.next_question_hint or None,
            "screening_result": screening_payload,
            "citations": [
                {"title": c.title, "snippet": c.snippet[:280], "url": c.url} for c in citations[:3]
            ]
            if terminal or policy_answer_context
            else [],
            "policy_context": policy_answer_context,
            "safety_note": safety_preamble,
            "ruleset_id": RULESET.id,
        },
        default=str,
    )
    text = chat_text(system=system, user=user, temperature=0.45)

    # Prefer model weaving; only hard-prepend if the model ignored a blocking safety note.
    if safety_preamble and safety_preamble.strip() and safety_preamble.strip() not in text:
        # For short safety notes, prepend; long blocks only if truly missing
        text = safety_preamble.strip() + "\n\n" + text

    if should_append_disclaimer(case, assessment):
        lower = text.lower()
        if "informal" not in lower and "not an official" not in lower and "dss" not in lower:
            text = text.rstrip() + "\n\n" + DISCLAIMER
        case.disclaimer_given = True

    return text
