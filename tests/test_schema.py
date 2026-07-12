"""Extraction schema coercion (deterministic, no LLM)."""

from __future__ import annotations

from src.extraction.schema import coerce_extraction, empty_facts


def test_empty_facts_has_confidence() -> None:
    facts = empty_facts()
    assert facts["confidence"] == {}


def test_coerce_non_dict() -> None:
    result = coerce_extraction("not json")
    assert result["user_intents"] == ["eligibility_screening"]
    assert "facts" in result


def test_coerce_nested_facts() -> None:
    result = coerce_extraction(
        {
            "facts": {
                "lives_in_nc": True,
                "household_size": "3",
                "income_amount": "2500.5",
                "income_period": "monthly",
                "gross_or_net": "gross",
                "household_or_individual": "household",
                "is_student": False,
                "confidence": {"income_amount": "0.85"},
            },
            "user_intents": ["eligibility_screening", "policy_question"],
            "policy_question": "What counts as income?",
            "notes": "ok",
        }
    )
    facts = result["facts"]
    assert facts["lives_in_nc"] is True
    assert facts["household_size"] == 3
    assert facts["income_amount"] == 2500.5
    assert facts["income_period"] == "monthly"
    assert facts["gross_or_net"] == "gross"
    assert facts["confidence"]["income_amount"] == 0.85
    assert result["user_intents"] == ["eligibility_screening", "policy_question"]
    assert result["policy_question"] == "What counts as income?"


def test_coerce_flat_facts_object() -> None:
    result = coerce_extraction({"lives_in_nc": 1, "household_size": 2.0})
    assert result["facts"]["lives_in_nc"] is True
    assert result["facts"]["household_size"] == 2
    assert result["user_intents"] == ["eligibility_screening"]


def test_coerce_rejects_bad_period_and_bool_as_int() -> None:
    result = coerce_extraction(
        {
            "facts": {
                "income_period": "hourly",  # not a supported period
                "household_size": True,  # bool must not become 1
                "income_amount": False,
            }
        }
    )
    facts = result["facts"]
    assert "income_period" not in facts or facts.get("income_period") is None
    assert "household_size" not in facts or facts.get("household_size") is None
    assert "income_amount" not in facts or facts.get("income_amount") is None


def test_coerce_accepts_daily_period() -> None:
    result = coerce_extraction(
        {
            "facts": {
                "income_amount": 200,
                "income_period": "daily",
            }
        }
    )
    facts = result["facts"]
    assert facts.get("income_amount") == 200
    assert facts.get("income_period") == "daily"


def test_coerce_confirm_fields() -> None:
    result = coerce_extraction(
        {
            "facts": {
                "confirm_field": "household_size",
                "confirm_value": 4,
            }
        }
    )
    assert result["facts"]["confirm_field"] == "household_size"
    assert result["facts"]["confirm_value"] == 4


def test_coerce_ignores_garbage_confidence() -> None:
    result = coerce_extraction({"facts": {"confidence": {"x": "nope", 1: 0.5}}})
    assert result["facts"]["confidence"] == {}
