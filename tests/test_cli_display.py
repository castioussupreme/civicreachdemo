"""CLI assessment card formatting (no LLM)."""

from __future__ import annotations

from src.cli_display import format_assessment_card, should_show_assessment_card
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus


def _assessment(**kwargs: object) -> Assessment:
    base = {
        "status": AssessmentStatus.LIKELY_ELIGIBLE,
        "reasons": [
            "Normalized gross monthly income $3,000.00 is at or below "
            "the public screening threshold $3,526.00 for a household of 2."
        ],
        "rule_version": "nc-fns-screening-2025-10",
        "source_ids": ["nc-fns-income-limits"],
        "threshold_used": 3526.0,
        "normalized_gross_monthly": 3000.0,
        "household_size": 2,
        "caveats": ["This is an informal screening only."],
    }
    base.update(kwargs)
    return Assessment(**base)  # type: ignore[arg-type]


def test_format_assessment_card_is_user_friendly() -> None:
    card = format_assessment_card(_assessment(), program_slug="nc-fns")
    assert "Likely eligible" in card
    assert "(screening)" not in card
    assert "code-owned" not in card.lower()
    assert "Ruleset" not in card
    assert "nc-fns-screening" not in card
    assert "What we used for this screen" in card
    assert "Household size: 2 people" in card
    assert "Monthly income used: $3,000" in card
    assert "Public income limit: $3,526" in card
    assert "Your estimated monthly income" in card
    assert "public income limit" in card
    assert "Normalized gross" not in card
    assert "Informal screen only" in card
    assert "County DSS decides" in card
    # Resolves assessment.source_ids to real title + URL (needs program_slug)
    assert "Public sources" in card
    assert "morefood.org" in card
    assert "nc-fns-income-limits" not in card


def test_format_assessment_card_with_citations() -> None:
    cites = [
        Citation(
            source_id="nc-fns-income-limits",
            title="Income limits",
            url="https://example.com/limits",
            snippet="table",
        )
    ]
    card = format_assessment_card(_assessment(), citations=cites)
    assert "Public sources" in card
    assert "Income limits" in card
    assert "https://example.com/limits" in card
    assert "[nc-fns-income-limits]" not in card


def test_should_show_card_only_for_terminal() -> None:
    assert should_show_assessment_card(_assessment()) is True
    assert (
        should_show_assessment_card(_assessment(status=AssessmentStatus.NEEDS_MORE_INFORMATION))
        is False
    )
    assert should_show_assessment_card(None) is False
