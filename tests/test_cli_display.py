"""CLI assessment card formatting (no LLM)."""

from __future__ import annotations

from src.cli_display import format_assessment_card, should_show_assessment_card
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus


def _assessment(**kwargs: object) -> Assessment:
    base = {
        "status": AssessmentStatus.LIKELY_ELIGIBLE,
        "reasons": ["Income under threshold."],
        "rule_version": "nc-fns-screening-2025-10",
        "source_ids": ["nc-fns-income-limits"],
        "threshold_used": 3526.0,
        "normalized_gross_monthly": 3000.0,
        "household_size": 2,
        "caveats": ["This is an informal screening only."],
    }
    base.update(kwargs)
    return Assessment(**base)  # type: ignore[arg-type]


def test_format_assessment_card_includes_math() -> None:
    card = format_assessment_card(_assessment())
    assert "Likely eligible" in card
    assert "$3,000.00" in card
    assert "$3,526.00" in card
    assert "Household size: 2" in card
    assert "Income under threshold" in card


def test_format_assessment_card_with_citations() -> None:
    cites = [
        Citation(
            source_id="nc-fns-income-limits",
            title="Income limits",
            url="https://example.com",
            snippet="table",
        )
    ]
    card = format_assessment_card(_assessment(), citations=cites)
    assert "Sources:" in card
    assert "nc-fns-income-limits" in card


def test_should_show_card_only_for_terminal() -> None:
    assert should_show_assessment_card(_assessment()) is True
    assert (
        should_show_assessment_card(_assessment(status=AssessmentStatus.NEEDS_MORE_INFORMATION))
        is False
    )
    assert should_show_assessment_card(None) is False
