"""CLI presentation helpers (no I/O beyond formatting strings)."""

from __future__ import annotations

from src.compose.response import is_terminal_assessment
from src.retrieval.kb import Citation, format_citations
from src.state.models import Assessment, AssessmentStatus

STATUS_LABELS = {
    AssessmentStatus.LIKELY_ELIGIBLE: "Likely eligible (screening)",
    AssessmentStatus.LIKELY_INELIGIBLE: "Likely not eligible (screening)",
    AssessmentStatus.NEEDS_MORE_INFORMATION: "Need more information",
    AssessmentStatus.UNABLE_TO_DETERMINE: "Unable to determine with confidence",
}


def format_assessment_card(
    assessment: Assessment,
    *,
    citations: list[Citation] | None = None,
) -> str:
    """Code-owned summary so reviewers can see the math without trusting the chat prose."""
    label = STATUS_LABELS.get(assessment.status, assessment.status.value)
    lines = [
        f"Result:  {label}",
        f"Ruleset: {assessment.rule_version}",
    ]
    if assessment.household_size is not None:
        lines.append(f"Household size: {assessment.household_size}")
    if assessment.normalized_gross_monthly is not None:
        lines.append(f"Monthly figure used: ${assessment.normalized_gross_monthly:,.2f}")
    if assessment.threshold_used is not None:
        lines.append(f"Public gross threshold: ${assessment.threshold_used:,.2f}")
    if assessment.reasons:
        lines.append("Why:")
        for r in assessment.reasons[:4]:
            lines.append(f"  • {r}")
    soft_caveats = [
        c for c in assessment.caveats if "informal" not in c.lower() and "ruleset" not in c.lower()
    ][:3]
    if soft_caveats:
        lines.append("Notes:")
        for c in soft_caveats:
            lines.append(f"  • {c}")
    if citations:
        cite = format_citations(citations)
        if cite:
            lines.append(cite)
    lines.append("Informal screen only — county DSS decides.")
    return "\n".join(lines)


def should_show_assessment_card(assessment: Assessment | None) -> bool:
    return is_terminal_assessment(assessment)
