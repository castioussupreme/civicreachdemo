"""
Structured grounding for terminal compose replies.

The LLM still writes conversational English in `message`, and also returns a
`grounding` receipt that must equal the code-owned assessment (required_facts).
On mismatch: one repair, then a template fallback (never invents numbers).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from src.compose.copy import resolve_program
from src.json_types import JsonObject, JsonValue
from src.retrieval.kb import Citation, public_citation_dicts
from src.state.models import Assessment, AssessmentStatus

logger = logging.getLogger(__name__)

# Keys the model must echo when present on the assessment
GroundingKey = Literal["status", "monthly_income", "threshold", "household_size"]

_MONEY_KEYS = frozenset({"monthly_income", "threshold"})
_FLOAT_TOL = 0.02


@dataclass(frozen=True)
class GroundingCheck:
    ok: bool
    issues: tuple[str, ...]


def required_facts(assessment: Assessment) -> dict[str, str | int | float]:
    """
    Closed fact bag derived only from the assessment.

    Null fields are omitted — the model must not invent them in grounding.
    """
    facts: dict[str, str | int | float] = {"status": assessment.status.value}
    if assessment.normalized_gross_monthly is not None:
        facts["monthly_income"] = float(assessment.normalized_gross_monthly)
    if assessment.threshold_used is not None:
        facts["threshold"] = float(assessment.threshold_used)
    if assessment.household_size is not None:
        facts["household_size"] = int(assessment.household_size)
    return facts


def validate_grounding(
    grounding: object,
    required: dict[str, str | int | float],
) -> GroundingCheck:
    """Generic equality check: grounding receipt vs required_facts."""
    if not isinstance(grounding, dict):
        return GroundingCheck(ok=False, issues=("grounding_not_object",))

    issues: list[str] = []
    for key, expected in required.items():
        if key not in grounding:
            issues.append(f"missing:{key}")
            continue
        actual = grounding[key]
        if key == "status":
            if str(actual) != str(expected):
                issues.append(f"mismatch:status:{actual!r}!={expected!r}")
            continue
        if key in _MONEY_KEYS or isinstance(expected, float):
            try:
                if abs(float(actual) - float(expected)) > _FLOAT_TOL:
                    issues.append(f"mismatch:{key}:{actual!r}!={expected!r}")
            except (TypeError, ValueError):
                issues.append(f"invalid:{key}:{actual!r}")
            continue
        try:
            if int(actual) != int(expected):
                issues.append(f"mismatch:{key}:{actual!r}!={expected!r}")
        except (TypeError, ValueError):
            issues.append(f"invalid:{key}:{actual!r}")

    ok = len(issues) == 0
    if not ok:
        logger.info("compose grounding failed: %s", "; ".join(issues))
    return GroundingCheck(ok=ok, issues=tuple(issues))


def parse_compose_json(payload: JsonObject) -> tuple[str | None, JsonValue | None]:
    """Extract message + grounding from a compose JSON object."""
    raw_msg = payload.get("message")
    message = raw_msg.strip() if isinstance(raw_msg, str) and raw_msg.strip() else None
    grounding = payload.get("grounding")
    return message, grounding


def template_terminal_reply(
    assessment: Assessment,
    *,
    citations: list[Citation] | None = None,
    include_disclaimer: bool = True,
    disclaimer: str = "",
    program_slug: str = "",
) -> str:
    """
    Graceful failure: code-owned prose from the assessment only.

    No LLM. Numbers only from assessment. User still gets a correct answer.
    """
    size = assessment.household_size
    monthly = assessment.normalized_gross_monthly
    threshold = assessment.threshold_used
    prog = resolve_program(program_slug) if program_slug else None
    agency = (prog.apply_channel if prog and prog.apply_channel else "") or "the agency"
    next_apply = ""
    if prog and prog.apply_label and prog.apply_url:
        next_apply = f" Applying via {prog.apply_label} ({prog.apply_url}) or {agency} is the reliable next step."
    elif prog and prog.apply_url:
        next_apply = (
            f" Applying at {prog.apply_url} or contacting {agency} is the reliable next step."
        )
    else:
        next_apply = f" Contacting {agency} is the reliable next step."

    parts: list[str] = []
    if size is not None and monthly is not None and threshold is not None:
        people = "person" if size == 1 else "people"
        parts.append(
            f"Based on what you shared, for a household of {size} {people}, "
            f"we used about {_money(monthly)} in monthly income against a public "
            f"income limit of {_money(threshold)}."
        )
    elif monthly is not None and threshold is not None:
        parts.append(
            f"Based on what you shared, we used about {_money(monthly)} in monthly "
            f"income against a public income limit of {_money(threshold)}."
        )
    elif threshold is not None:
        parts.append(
            f"Based on what you shared, the public income limit we used is {_money(threshold)}."
        )

    if assessment.status == AssessmentStatus.LIKELY_ELIGIBLE:
        parts.append(
            "On this informal public income screen, that looks like you may qualify — "
            f"only {agency} can decide for real."
        )
    elif assessment.status == AssessmentStatus.LIKELY_INELIGIBLE:
        parts.append(
            "On this informal public income screen, that looks like you may not qualify — "
            f"only {agency} can decide for real."
        )
    else:
        extra = ""
        if assessment.reasons:
            extra = f" {assessment.reasons[0].rstrip('.')}."
        parts.append(
            "I can't give a confident yes or no from this simple screen." + extra + next_apply
        )

    for c in public_citation_dicts(
        citations,
        source_ids=assessment.source_ids,
        limit=2,
        program_slug=program_slug,
    ):
        title = c.get("title") or "Public source"
        url = c.get("url")
        if url:
            parts.append(f"More: {title} — {url}")
        else:
            parts.append(f"More: {title}")

    if include_disclaimer and disclaimer:
        parts.append(disclaimer)

    return "\n\n".join(parts)


def _money(amount: float) -> str:
    if float(amount).is_integer():
        return f"${int(amount):,}"
    return f"${amount:,.2f}"
