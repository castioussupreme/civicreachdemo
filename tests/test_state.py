"""Case state updates and field semantics (no LLM, no planner)."""

from __future__ import annotations

from src.state.models import CaseField, EligibilityCase, FieldStatus
from src.state.updates import apply_validated_updates


def test_apply_income_and_normalize_monthly() -> None:
    case = EligibilityCase()
    case = apply_validated_updates(
        case,
        {
            "facts": {
                "lives_in_nc": True,
                "household_size": 2,
                "income_amount": 2500,
                "income_period": "monthly",
                "gross_or_net": "gross",
                "household_or_individual": "household",
                "confidence": {
                    "lives_in_nc": 0.9,
                    "household_size": 0.9,
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                    "household_or_individual": 0.9,
                },
            }
        },
        turn=1,
    )
    assert case.household_size.value == 2
    assert case.normalized_gross_monthly.status == FieldStatus.KNOWN
    assert case.normalized_gross_monthly.value == 2500


def test_normalize_weekly_and_annual() -> None:
    weekly = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "income_amount": 500,
                "income_period": "weekly",
                "gross_or_net": "gross",
                "confidence": {
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                },
            }
        },
        turn=1,
    )
    assert weekly.normalized_gross_monthly.value == round(500 * 52 / 12, 2)

    annual = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "income_amount": 36000,
                "income_period": "annual",
                "gross_or_net": "gross",
                "confidence": {
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                },
            }
        },
        turn=1,
    )
    assert annual.normalized_gross_monthly.value == 3000.0


def test_normalize_daily_two_hundred_a_day() -> None:
    """\"200 a day\" → daily period → monthly = 200 * 365 / 12."""
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "income_amount": 200,
                "income_period": "daily",
                "gross_or_net": "gross",
                "household_or_individual": "household",
                "confidence": {
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                    "household_or_individual": 0.9,
                },
            }
        },
        turn=1,
    )
    assert case.income_period.value == "daily"
    assert case.normalized_gross_monthly.status == FieldStatus.KNOWN
    assert case.normalized_gross_monthly.value == round(200 * 365 / 12, 2)


def test_uncertain_about_income() -> None:
    case = EligibilityCase()
    case = apply_validated_updates(
        case,
        {
            "facts": {
                "income_amount": 2500,
                "confidence": {"income_amount": 0.4},
            }
        },
        turn=1,
    )
    assert case.income_amount.status == FieldStatus.UNCERTAIN
    assert case.income_amount.value == 2500


def test_contradiction_on_household_size() -> None:
    case = EligibilityCase()
    case = apply_validated_updates(
        case,
        {"facts": {"household_size": 2, "confidence": {"household_size": 0.9}}},
        turn=1,
    )
    case = apply_validated_updates(
        case,
        {"facts": {"household_size": 4, "confidence": {"household_size": 0.9}}},
        turn=2,
    )
    assert case.household_size.status == FieldStatus.CONFLICTING
    assert case.household_size.value == 2  # previous kept until confirm
    open_c = [c for c in case.contradictions if not c.resolved]
    assert len(open_c) == 1
    assert open_c[0].previous_value == 2
    assert open_c[0].proposed_value == 4


def test_confirm_resolves_contradiction() -> None:
    case = EligibilityCase()
    case = apply_validated_updates(
        case,
        {"facts": {"household_size": 2, "confidence": {"household_size": 0.9}}},
        turn=1,
    )
    case = apply_validated_updates(
        case,
        {"facts": {"household_size": 4, "confidence": {"household_size": 0.9}}},
        turn=2,
    )
    case = apply_validated_updates(
        case,
        {
            "facts": {
                "confirm_field": "household_size",
                "confirm_value": 4,
            }
        },
        turn=3,
    )
    assert case.household_size.status == FieldStatus.KNOWN
    assert case.household_size.value == 4
    assert all(c.resolved for c in case.contradictions if c.field == "household_size")


def test_net_income_marks_normalized_uncertain() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "income_amount": 2000,
                "income_period": "monthly",
                "gross_or_net": "net",
                "confidence": {
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                },
            }
        },
        turn=1,
    )
    assert case.normalized_gross_monthly.status == FieldStatus.UNCERTAIN
    assert case.normalized_gross_monthly.value == 2000


def test_individual_income_multi_person_uncertain() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "household_size": 3,
                "income_amount": 2000,
                "income_period": "monthly",
                "gross_or_net": "gross",
                "household_or_individual": "individual",
                "confidence": {
                    "household_size": 0.9,
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                    "household_or_individual": 0.9,
                },
            }
        },
        turn=1,
    )
    assert case.normalized_gross_monthly.status == FieldStatus.UNCERTAIN


def test_implausible_household_size_ignored() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {"facts": {"household_size": 0, "confidence": {"household_size": 0.9}}},
        turn=1,
    )
    assert case.household_size.status == FieldStatus.UNKNOWN
    assert any("implausible" in n for n in case.notes)

    case2 = apply_validated_updates(
        EligibilityCase(),
        {"facts": {"household_size": 99, "confidence": {"household_size": 0.9}}},
        turn=1,
    )
    assert case2.household_size.status == FieldStatus.UNKNOWN


def test_implausible_income_ignored() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {"facts": {"income_amount": -5, "confidence": {"income_amount": 0.9}}},
        turn=1,
    )
    assert case.income_amount.status == FieldStatus.UNKNOWN


def test_invalid_period_ignored() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "income_amount": 1000,
                "income_period": "hourly",  # type: ignore[typeddict-item]
                "confidence": {"income_amount": 0.9, "income_period": 0.9},
            }
        },
        turn=1,
    )
    assert case.income_amount.status == FieldStatus.KNOWN
    assert case.income_period.status == FieldStatus.UNKNOWN
    assert case.normalized_gross_monthly.status == FieldStatus.UNKNOWN


def test_student_and_elderly_flags() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "is_student": True,
                "elderly_or_disabled_member": True,
                "confidence": {"is_student": 0.9, "elderly_or_disabled_member": 0.9},
            }
        },
        turn=1,
    )
    assert case.is_student.value is True
    assert case.elderly_or_disabled_member.value is True


def test_known_summary_serializable() -> None:
    case = apply_validated_updates(
        EligibilityCase(),
        {
            "facts": {
                "lives_in_nc": True,
                "household_size": 1,
                "income_amount": 1500,
                "income_period": "monthly",
                "gross_or_net": "gross",
                "confidence": {
                    "lives_in_nc": 0.9,
                    "household_size": 0.9,
                    "income_amount": 0.9,
                    "income_period": 0.9,
                    "gross_or_net": 0.9,
                },
            }
        },
        turn=1,
    )
    summary = case.known_summary()
    # Facts only — no stage labels (those are debug/API metadata)
    assert "stage" not in summary
    assert summary["lives_in_nc"]["value"] is True  # type: ignore[index]
    assert summary["household_size"]["value"] == 1  # type: ignore[index]
    assert "normalized_gross_monthly" in summary


def test_case_field_is_usable() -> None:
    unknown: CaseField[int] = CaseField()
    assert unknown.is_usable() is False
    known = CaseField(status=FieldStatus.KNOWN, value=3)
    assert known.is_usable() is True
    uncertain = CaseField(status=FieldStatus.UNCERTAIN, value=3)
    assert uncertain.is_usable() is False
