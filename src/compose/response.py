from __future__ import annotations

import json
import logging
from datetime import date

from src.compose.copy import next_steps_blurb, resolve_program, scope_intro_blurb
from src.compose.grounding import (
    parse_compose_json,
    required_facts,
    template_terminal_reply,
    validate_grounding,
)
from src.llm.client import chat_json, chat_text
from src.planner.missing import PlanResult
from src.retrieval.kb import Citation, public_citation_dicts
from src.state.models import Assessment, AssessmentStatus, EligibilityCase, Stage

logger = logging.getLogger(__name__)

# Soft line — only appended on a terminal screening result, and at most once per case.
# Prefer pack apply_channel when known; fallback is generic.
DISCLAIMER = (
    "Just a heads-up: this is an informal screen, not an official decision — "
    "the agency makes the final call."
)


def disclaimer_for_case(case: EligibilityCase) -> str:
    prog = resolve_program(case.program_slug)
    if prog is not None and prog.apply_channel:
        return (
            "Just a heads-up: this is an informal screen, not an official decision — "
            f"{prog.apply_channel} makes the final call."
        )
    return DISCLAIMER


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
            "clearly. Suggest applying so the agency can review, or sharing the missing detail if simple."
        ),
        AssessmentStatus.NEEDS_MORE_INFORMATION: (
            "Do not announce a status. Just ask for the missing detail naturally."
        ),
    }[status]


def _public_citation_payload(
    citations: list[Citation],
    *,
    program_slug: str = "",
) -> list[dict[str, str]]:
    """Title + URL only for the model (no internal source ids)."""
    return public_citation_dicts(citations, limit=3, program_slug=program_slug)


def compose_response(
    *,
    case: EligibilityCase,
    plan: PlanResult,
    assessment: Assessment | None,
    citations: list[Citation],
    safety_preamble: str | None = None,
    policy_answer_context: str | None = None,
    user_message: str | None = None,
    post_assess: bool = False,
) -> str:
    terminal = is_terminal_assessment(assessment)
    include_disclaimer_hint = should_append_disclaimer(case, assessment)
    # Already gave a terminal result earlier — follow-up chat, not a new interview
    if post_assess and assessment is not None:
        text = _compose_post_assess(
            case=case,
            assessment=assessment,
            plan=plan,
            citations=citations,
            safety_preamble=safety_preamble,
            policy_answer_context=policy_answer_context,
            user_message=user_message,
        )
    elif terminal and assessment is not None:
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

    # Prefer model weaving; if the model ignored the steer, prepend the short note.
    if safety_preamble and safety_preamble.strip():
        pre = safety_preamble.strip()
        # Avoid duplicating a long preamble when the model already refused
        refused = any(
            k in text.lower()
            for k in (
                "can't",
                "cannot",
                "outside what i can",
                "not related",
                "stick to",
                "ignore those limits",
            )
        )
        if pre not in text and not refused:
            follow = plan.next_question_hint or ""
            if follow and follow not in text:
                text = f"{pre} {follow}\n\n{text}".strip()
            else:
                text = f"{pre}\n\n{text}".strip()

    # Scope intro lives in the opening message (fresh_case). Backfill only if
    # somehow missing (e.g. tests that construct cases without fresh_case).
    if not case.scope_intro_given and case.stage != Stage.ASSESSED:
        prog = resolve_program(case.program_slug)
        if prog is not None:
            text = scope_intro_blurb(prog) + "\n\n" + text
            case.scope_intro_given = True

    if should_append_disclaimer(case, assessment):
        lower = text.lower()
        if "informal" not in lower and "not an official" not in lower:
            text = text.rstrip() + "\n\n" + disclaimer_for_case(case)
        case.disclaimer_given = True

    # Terminal assess: code-owned apply / agency next steps (once)
    if terminal and assessment is not None and not case.next_steps_given and not post_assess:
        prog = resolve_program(case.program_slug)
        if prog is not None:
            text = text.rstrip() + "\n\n" + next_steps_blurb(prog)
            case.next_steps_given = True

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
    prog = resolve_program(case.program_slug)
    agency = (prog.apply_channel if prog and prog.apply_channel else "") or "the agency"
    notice = (
        f"Note: the public income limits used here apply through {case.ruleset_effective_to}. "
        f"After that date, official limits may change — {agency} uses current rules."
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
    cite_payload = _public_citation_payload(citations, program_slug=case.program_slug)
    history = [{"role": t.role, "text": t.text} for t in case.recent_turns]

    prog = resolve_program(case.program_slug)
    program_label = (
        prog.display_name if prog is not None else (case.program_slug or "public benefits")
    )
    agency = (prog.apply_channel if prog is not None and prog.apply_channel else "") or "the agency"
    system = (
        f"You help someone check whether they might qualify for {program_label}.\n"
        "You are not a government worker and cannot submit applications.\n"
        "\n"
        "Respond with a single JSON object only:\n"
        '  {"message": "<conversational reply>", "grounding": { ... }}\n'
        "\n"
        "message: natural, friendly English (1-4 short sentences). Not a form.\n"
        "  - Share the screening outcome in plain words (use outcome_guidance).\n"
        "  - Mention monthly income and public threshold when they appear in required_facts.\n"
        "  - Never invent dollar amounts or thresholds.\n"
        "  - Never use internal ids (source_id, field names, ruleset ids).\n"
        "  - Citations: only title + URL from the citations list; optional "
        '"More: title — url" line.\n'
        + (
            f"  - End with a short note that this is informal and {agency} decides.\n"
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
            "ruleset_id": case.ruleset_id,
            "program_slug": case.program_slug,
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
        disclaimer=disclaimer_for_case(case),
        program_slug=case.program_slug,
    )


def _compose_post_assess(
    *,
    case: EligibilityCase,
    assessment: Assessment,
    plan: PlanResult,
    citations: list[Citation],
    safety_preamble: str | None,
    policy_answer_context: str | None,
    user_message: str | None,
) -> str:
    """
    After a terminal screen: answer questions / next steps without re-interviewing.
    """
    _ = plan
    prog = resolve_program(case.program_slug)
    next_steps = next_steps_blurb(prog) if prog is not None else ""
    history = [{"role": t.role, "text": t.text} for t in case.recent_turns]
    system = (
        "You already finished an informal eligibility screen for this person.\n"
        "Do NOT re-ask household size, income, residency, or restart the interview.\n"
        "You are not a government worker and cannot submit applications.\n"
        "\n"
        "VOICE: short, friendly, 1-3 sentences.\n"
        "FACTS: trust known_facts and prior_screening. Never invent dollar thresholds.\n"
        "If they ask how to apply or what to do next, point them to the next_steps text "
        "(use the real URL if present). If they only chit-chat, answer briefly and offer "
        "to clarify the prior screen — do not collect new screening fields unless they "
        "clearly correct a fact (then acknowledge; code will re-run the screen).\n"
    )
    user = json.dumps(
        {
            "mode": "post_assess_follow_up",
            "user_just_said": user_message,
            "conversation_history": history,
            "known_facts": case.known_summary(),
            "prior_screening": {
                "status": assessment.status.value,
                "reasons": list(assessment.reasons)[:3],
                "monthly_income": assessment.normalized_gross_monthly,
                "threshold": assessment.threshold_used,
                "household_size": assessment.household_size,
            },
            "next_steps": next_steps,
            "policy_context": policy_answer_context,
            "citations": (
                _public_citation_payload(citations, program_slug=case.program_slug)
                if policy_answer_context
                else []
            ),
            "safety_note": safety_preamble,
            "program_slug": case.program_slug,
        },
        default=str,
    )
    return chat_text(system=system, user=user, temperature=0.4)


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

    prog = resolve_program(case.program_slug)
    program_label = (
        prog.display_name if prog is not None else (case.program_slug or "public benefits")
    )
    area = prog.service_area_name if prog is not None else "the program area"
    agency = (prog.apply_channel if prog is not None and prog.apply_channel else "") or "the agency"

    system = (
        f"You are a friendly person helping someone check whether they might qualify for "
        f"{program_label} ({area}). You are not a government worker and "
        "you cannot submit applications.\n"
        "\n"
        "VOICE (critical):\n"
        "- Talk like a helpful human texting, not a form, portal, or call-center script.\n"
        "- Short messages: usually 1-3 sentences during intake.\n"
        "- Acknowledge what they just said in natural words, then one clear next step or question.\n"
        "- Never use robotic section headers, bullet status labels, or phrases like "
        '"Need more information", "Likely eligible (screening)", "Status:", '
        '"Assessment:", or "Unofficial determination".\n'
        "- Never list internal field names (lives_in_service_area, income_period, ruleset ids).\n"
        "- Do not repeat a full legal disclaimer every turn. "
        + (
            f"On this turn only, end with one short plain-language note that this is informal "
            f"and {agency} decides.\n"
            if include_disclaimer_hint
            else "Skip disclaimers on this turn — it was already covered or not needed yet.\n"
        )
        + "\n"
        "FACTS (critical):\n"
        "- known_facts is the source of truth. conversation_history is only for wording and continuity.\n"
        "- If history and known_facts disagree, trust known_facts.\n"
        "- Never invent dollar thresholds or rules.\n"
        "- Never claim you filed an application or contacted the agency.\n"
        "\n"
        "CITATIONS (when the citations list is non-empty):\n"
        "- Use only the provided title and full URL — never invent links.\n"
        "- Never mention internal ids.\n"
        "\n"
        "SAFETY STEER (when safety_note is present):\n"
        "- Lead with a short refuse/steer (you may rephrase safety_note).\n"
        "- Then ask next_question_hint as the follow-up — do not only repeat the refuse line.\n"
        "- Do not answer off-topic questions (no math, jokes, other topics).\n"
        "\n"
        "THIS TURN mode="
        + mode
        + ":\n"
        + (
            "- Ask exactly ONE natural question (use next_question_hint as the *idea*, rephrase freely).\n"
            "- NEVER paste next_question_hint word-for-word if the user just answered (even vaguely).\n"
            "- If user_just_said is fuzzy (maybe, not sure, it depends): acknowledge that first, "
            "briefly explain why a simple yes/no helps this screen, then ask a clearer version.\n"
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
            "field_status_hint": _field_status_hint(case, plan),
            "screening_result": screening_payload,
            "citations": (
                _public_citation_payload(citations, program_slug=case.program_slug)
                if policy_answer_context
                else []
            ),
            "policy_context": policy_answer_context,
            "safety_note": safety_preamble,
            "ruleset_id": case.ruleset_id,
            "program_slug": case.program_slug,
        },
        default=str,
    )
    return chat_text(system=system, user=user, temperature=0.45)


def _field_status_hint(case: EligibilityCase, plan: PlanResult) -> str | None:
    """Tell compose when the primary missing slot is uncertain / needs soft clarify."""
    if not plan.missing_fields:
        return None
    primary = plan.missing_fields[0]
    if primary.startswith("confirm_conflict"):
        return "conflict_confirm"
    field = getattr(case, primary, None)
    if field is None:
        return None
    status = getattr(field, "status", None)
    if status is None:
        return None
    status_val = status.value if hasattr(status, "value") else str(status)
    if status_val == "uncertain":
        return f"{primary}_uncertain"
    return None
