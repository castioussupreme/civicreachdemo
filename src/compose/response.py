from __future__ import annotations

import json
import logging
from datetime import date

from src.compose.grounding import (
    parse_compose_json,
    required_facts,
    template_terminal_reply,
    validate_grounding,
)
from src.eligibility.ruleset import RULESET
from src.llm.client import chat_json, chat_text
from src.planner.missing import PlanResult
from src.retrieval.kb import Citation, public_citation_dicts
from src.state.models import Assessment, AssessmentStatus, EligibilityCase

logger = logging.getLogger(__name__)

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


def _public_citation_payload(citations: list[Citation]) -> list[dict[str, str]]:
    """Title + URL only for the model (no internal source ids)."""
    return public_citation_dicts(citations, limit=3)


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

    if terminal and assessment is not None:
        text = _compose_terminal(
            case=case,
            assessment=assessment,
            citations=citations,
            safety_preamble=safety_preamble,
            user_message=user_message,
            include_disclaimer_hint=include_disclaimer_hint,
        )
    else:
        text = _compose_intake(
            case=case,
            plan=plan,
            assessment=assessment,
            citations=citations,
            safety_preamble=safety_preamble,
            policy_answer_context=policy_answer_context,
            user_message=user_message,
            include_disclaimer_hint=include_disclaimer_hint,
        )

    # Prefer model weaving; only hard-prepend if the model ignored a blocking safety note.
    if safety_preamble and safety_preamble.strip() and safety_preamble.strip() not in text:
        text = safety_preamble.strip() + "\n\n" + text

    if should_append_disclaimer(case, assessment):
        lower = text.lower()
        if "informal" not in lower and "not an official" not in lower and "dss" not in lower:
            text = text.rstrip() + "\n\n" + DISCLAIMER
        case.disclaimer_given = True

    # Near FY end: one plain-language period notice (only when effective_to is set)
    text = _maybe_append_period_notice(case, text)

    return text


def _maybe_append_period_notice(case: EligibilityCase, text: str) -> str:
    if case.period_notice_given:
        return text
    if not case.ruleset_effective_to or not case.as_of:
        return text
    try:
        as_of = date.fromisoformat(case.as_of)
        end = date.fromisoformat(case.ruleset_effective_to)
    except ValueError:
        return text
    days = (end - as_of).days
    if days < 0 or days > 30:
        return text
    notice = (
        f"Note: the public income limits used here apply through {case.ruleset_effective_to}. "
        "After that date, official limits may change — DSS uses current rules."
    )
    case.period_notice_given = True
    if "through" in text.lower() and case.ruleset_effective_to in text:
        return text
    return text.rstrip() + "\n\n" + notice


def _compose_terminal(
    *,
    case: EligibilityCase,
    assessment: Assessment,
    citations: list[Citation],
    safety_preamble: str | None,
    user_message: str | None,
    include_disclaimer_hint: bool,
) -> str:
    """
    Option 1: conversational message + structured grounding receipt.

    Validate grounding == required_facts; one repair; else template.
    """
    required = required_facts(assessment)
    cite_payload = _public_citation_payload(citations)
    history = [{"role": t.role, "text": t.text} for t in case.recent_turns]

    system = (
        "You help someone check North Carolina FNS (food assistance) eligibility.\n"
        "You are not a government worker and cannot submit applications.\n"
        "\n"
        "Respond with a single JSON object only:\n"
        '  {"message": "<conversational reply>", "grounding": { ... }}\n'
        "\n"
        "message: natural, friendly English (1-4 short sentences). Not a form.\n"
        "  - Share the screening outcome in plain words (use outcome_guidance).\n"
        "  - Mention monthly income and public threshold when they appear in required_facts.\n"
        "  - Never invent dollar amounts or thresholds.\n"
        "  - Never use internal ids (nc-fns-..., source_id, field names).\n"
        "  - Citations: only title + URL from the citations list; optional "
        '"More: title — url" line.\n'
        + (
            "  - End with a short note that this is informal and DSS decides.\n"
            if include_disclaimer_hint
            else "  - Skip long legal disclaimers (already covered or not needed).\n"
        )
        + "\n"
        "grounding: MUST exactly match required_facts (same keys and values).\n"
        "  Copy numbers and status from required_facts only — do not invent keys.\n"
        "  status must be the exact string from required_facts.\n"
    )

    user = json.dumps(
        {
            "mode": "share_screening_result",
            "user_just_said": user_message,
            "conversation_history": history,
            "known_facts": case.known_summary(),
            "required_facts": required,
            "outcome_guidance": _friendly_outcome(assessment.status),
            "reasons": list(assessment.reasons),
            "extra_notes": [
                c
                for c in assessment.caveats
                if "informal screening" not in c.lower() and "not an official" not in c.lower()
            ][:4],
            "citations": cite_payload,
            "safety_note": safety_preamble,
            "ruleset_id": RULESET.id,
        },
        default=str,
    )

    payload = chat_json(system=system, user=user, temperature=0.45)
    message, grounding = parse_compose_json(payload)
    check = validate_grounding(grounding, required)

    if message is not None and check.ok:
        logger.debug("compose grounding ok on first try")
        return message

    # One repair: required_facts + draft only (no full history)
    issues = list(check.issues)
    if message is None:
        issues = ["missing_or_empty_message", *issues]

    logger.info("compose grounding repair: %s", "; ".join(issues) or "unknown")
    repair_system = (
        "Fix a screening reply. Return JSON only:\n"
        '  {"message": "<conversational English>", "grounding": { ... }}\n'
        "grounding MUST exactly match required_facts (keys and values).\n"
        "message must stay natural and friendly, use only those numbers/status,\n"
        "and not invent other dollar amounts. No internal ids."
    )
    repair_user = json.dumps(
        {
            "required_facts": required,
            "issues": issues,
            "draft_message": message,
            "draft_grounding": grounding,
            "user_just_said": user_message,
            "outcome_guidance": _friendly_outcome(assessment.status),
            "citations": cite_payload,
        },
        default=str,
    )
    repair_payload = chat_json(system=repair_system, user=repair_user, temperature=0.2)
    repair_message, repair_grounding = parse_compose_json(repair_payload)
    repair_check = validate_grounding(repair_grounding, required)

    if repair_message is not None and repair_check.ok:
        logger.debug("compose grounding ok after repair")
        return repair_message

    # Graceful failure: code template from assessment
    logger.warning(
        "compose grounding fallback to template: %s",
        "; ".join(repair_check.issues) if repair_message else "missing_message",
    )
    return template_terminal_reply(
        assessment,
        citations=citations,
        include_disclaimer=include_disclaimer_hint,
        disclaimer=DISCLAIMER,
    )


def _compose_intake(
    *,
    case: EligibilityCase,
    plan: PlanResult,
    assessment: Assessment | None,
    citations: list[Citation],
    safety_preamble: str | None,
    policy_answer_context: str | None,
    user_message: str | None,
    include_disclaimer_hint: bool,
) -> str:
    """Non-terminal turns: free-text compose (no grounding JSON)."""
    if assessment is not None and assessment.status == AssessmentStatus.NEEDS_MORE_INFORMATION:
        mode = "ask_follow_up"
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
        "- Short messages: usually 1-3 sentences during intake.\n"
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
        "- Never invent dollar thresholds or rules.\n"
        "- Never claim you filed an application or contacted DSS.\n"
        "\n"
        "CITATIONS (when the citations list is non-empty):\n"
        "- Use only the provided title and full URL — never invent links.\n"
        "- Never mention internal ids.\n"
        "\n"
        "THIS TURN mode="
        + mode
        + ":\n"
        + (
            "- Ask exactly ONE natural question (use next_question_hint as the idea, rephrase freely).\n"
            "- Do not recap every known fact. Do not say you still need more information as a status.\n"
            if mode in {"collect_info", "ask_follow_up"}
            else "- Answer using policy_context only, briefly, then continue intake if needed.\n"
            "- If citations include title and URL, you may add one short More: title — url line.\n"
        )
    )

    history = [{"role": t.role, "text": t.text} for t in case.recent_turns]

    screening_payload: dict[str, object] | None = None
    if assessment is not None and assessment.status == AssessmentStatus.NEEDS_MORE_INFORMATION:
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
            "citations": _public_citation_payload(citations) if policy_answer_context else [],
            "policy_context": policy_answer_context,
            "safety_note": safety_preamble,
            "ruleset_id": RULESET.id,
        },
        default=str,
    )
    return chat_text(system=system, user=user, temperature=0.45)
