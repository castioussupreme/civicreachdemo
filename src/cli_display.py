"""CLI presentation helpers (no I/O beyond formatting strings)."""

from __future__ import annotations

import re

from src.compose.response import is_terminal_assessment
from src.retrieval.kb import (
    Citation,
    format_citations,
    public_citations_from_ids,
)
from src.state.models import Assessment, AssessmentStatus

STATUS_LABELS = {
    AssessmentStatus.LIKELY_ELIGIBLE: "Likely eligible",
    AssessmentStatus.LIKELY_INELIGIBLE: "Likely not eligible",
    AssessmentStatus.NEEDS_MORE_INFORMATION: "Need more information",
    AssessmentStatus.UNABLE_TO_DETERMINE: "Unable to determine right now",
}


def format_assessment_card(
    assessment: Assessment,
    *,
    citations: list[Citation] | None = None,
) -> str:
    """Human-facing screening card (plain language; no backend jargon)."""
    label = STATUS_LABELS.get(assessment.status, assessment.status.value)
    lines = [label, ""]

    facts: list[str] = []
    if assessment.household_size is not None:
        n = assessment.household_size
        people = "person" if n == 1 else "people"
        facts.append(f"  Household size: {n} {people}")
    if assessment.normalized_gross_monthly is not None:
        facts.append(f"  Monthly income used: {_money(assessment.normalized_gross_monthly)}")
    if assessment.threshold_used is not None:
        facts.append(f"  Public income limit: {_money(assessment.threshold_used)}")
    if facts:
        lines.append("What we used for this screen")
        lines.extend(facts)
        lines.append("")

    if assessment.reasons:
        lines.append("Why")
        for r in assessment.reasons[:4]:
            lines.append(f"  • {_friendly_reason(r)}")
        lines.append("")

    soft_caveats = [
        c
        for c in assessment.caveats
        if "informal" not in c.lower()
        and "ruleset" not in c.lower()
        and "not an official" not in c.lower()
    ][:3]
    if soft_caveats:
        lines.append("Keep in mind")
        for c in soft_caveats:
            lines.append(f"  • {_friendly_reason(c)}")
        lines.append("")

    display_cites = citations
    if display_cites is None and assessment.source_ids:
        display_cites = public_citations_from_ids(assessment.source_ids)
    if display_cites:
        cite = format_citations(display_cites)
        if cite:
            lines.append(cite)
            lines.append("")

    lines.append("Informal screen only — not an official determination. County DSS decides.")
    # Drop trailing blank lines for a tight panel
    while lines and lines[-1] == "":
        lines.pop()
    # Collapse double blanks created by empty sections at end
    cleaned: list[str] = []
    for line in lines:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def should_show_assessment_card(assessment: Assessment | None) -> bool:
    return is_terminal_assessment(assessment)


def _money(amount: float) -> str:
    if float(amount).is_integer():
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _friendly_reason(text: str) -> str:
    """Light wording cleanup for engine/API reason strings shown to people."""
    out = text
    replacements = (
        ("Normalized gross monthly income", "Your estimated monthly income"),
        ("normalized gross monthly income", "estimated monthly income"),
        ("public screening threshold", "public income limit"),
        ("Public screening threshold", "Public income limit"),
        ("gross household monthly income", "monthly household income"),
        ("Gross household monthly income", "Monthly household income"),
        ("DSS decides", "your county DSS decides"),
    )
    for old, new in replacements:
        out = out.replace(old, new)
    # Avoid "your county your county"
    out = out.replace("your county your county", "your county")
    # Whole dollars without trailing .00 in reason prose
    return re.sub(r"\$(\d{1,3}(?:,\d{3})*)\.00\b", r"$\1", out)
