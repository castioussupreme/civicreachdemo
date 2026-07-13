"""Structured compose grounding (no LLM)."""

from __future__ import annotations

from src.compose.grounding import (
    parse_compose_json,
    required_facts,
    template_terminal_reply,
    validate_grounding,
)
from src.retrieval.kb import Citation
from src.state.models import Assessment, AssessmentStatus


def _assessment(**kwargs: object) -> Assessment:
    base: dict[str, object] = {
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


def test_required_facts_from_assessment() -> None:
    facts = required_facts(_assessment())
    assert facts == {
        "status": "likely_eligible",
        "monthly_income": 3000.0,
        "threshold": 3526.0,
        "household_size": 2,
    }


def test_required_facts_omits_null_money() -> None:
    facts = required_facts(
        _assessment(
            status=AssessmentStatus.LIKELY_INELIGIBLE,
            normalized_gross_monthly=None,
            threshold_used=None,
            household_size=None,
        )
    )
    assert facts == {"status": "likely_ineligible"}


def test_validate_grounding_ok() -> None:
    required = required_facts(_assessment())
    check = validate_grounding(
        {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 3526.0,
            "household_size": 2,
        },
        required,
    )
    assert check.ok
    assert check.issues == ()


def test_validate_grounding_float_tolerance() -> None:
    required = required_facts(_assessment())
    check = validate_grounding(
        {
            "status": "likely_eligible",
            "monthly_income": 3000.01,
            "threshold": 3526.0,
            "household_size": 2,
        },
        required,
    )
    assert check.ok


def test_validate_grounding_status_mismatch() -> None:
    required = required_facts(_assessment())
    check = validate_grounding(
        {
            "status": "likely_ineligible",
            "monthly_income": 3000,
            "threshold": 3526,
            "household_size": 2,
        },
        required,
    )
    assert not check.ok
    assert any(i.startswith("mismatch:status") for i in check.issues)


def test_validate_grounding_wrong_threshold() -> None:
    required = required_facts(_assessment())
    check = validate_grounding(
        {
            "status": "likely_eligible",
            "monthly_income": 3000,
            "threshold": 2610,  # size-1 table row — wrong for HH 2
            "household_size": 2,
        },
        required,
    )
    assert not check.ok
    assert any("threshold" in i for i in check.issues)


def test_validate_grounding_missing_keys() -> None:
    required = required_facts(_assessment())
    check = validate_grounding({"status": "likely_eligible"}, required)
    assert not check.ok
    assert any(i.startswith("missing:") for i in check.issues)


def test_validate_grounding_not_object() -> None:
    check = validate_grounding("nope", required_facts(_assessment()))
    assert not check.ok
    assert "grounding_not_object" in check.issues


def test_parse_compose_json() -> None:
    msg, g = parse_compose_json(
        {
            "message": "  You may qualify.  ",
            "grounding": {"status": "likely_eligible"},
        }
    )
    assert msg == "You may qualify."
    assert g == {"status": "likely_eligible"}


def test_parse_compose_json_empty_message() -> None:
    msg, _g = parse_compose_json({"message": "   ", "grounding": {}})
    assert msg is None


def test_template_includes_assessment_numbers() -> None:
    text = template_terminal_reply(
        _assessment(),
        citations=[
            Citation(
                source_id="nc-fns-income-limits",
                title="Income limits",
                url="https://example.com/limits",
                snippet="t",
            )
        ],
        include_disclaimer=True,
        disclaimer="Informal only — DSS decides.",
    )
    assert "$3,000" in text
    assert "$3,526" in text
    assert "2 people" in text or "household of 2" in text
    assert "may qualify" in text.lower()
    assert "https://example.com/limits" in text
    assert "DSS decides" in text
    assert "nc-fns-income-limits" not in text


def test_template_ineligible() -> None:
    text = template_terminal_reply(
        _assessment(status=AssessmentStatus.LIKELY_INELIGIBLE, normalized_gross_monthly=5000.0),
        include_disclaimer=False,
    )
    assert "may not qualify" in text.lower()
    assert "$5,000" in text
