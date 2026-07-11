"""Pure eligibility engine + income/ruleset (no LLM)."""

from __future__ import annotations

from typing import TypeVar

import pytest
from src.eligibility.engine import calculate_eligibility
from src.eligibility.income import normalize_to_monthly
from src.eligibility.ruleset import RULESET
from src.state.models import AssessmentStatus, CaseField, EligibilityCase, FieldStatus

T = TypeVar("T")


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def _uncertain(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.UNCERTAIN, value=value)


def test_normalize_income_all_periods() -> None:
    assert normalize_to_monthly(100, "weekly") == round(100 * 52 / 12, 2)
    assert normalize_to_monthly(1000, "biweekly") == round(1000 * 26 / 12, 2)
    assert normalize_to_monthly(2500, "monthly") == 2500
    assert normalize_to_monthly(60000, "annual") == 5000


def test_normalize_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        normalize_to_monthly(-1, "monthly")


def test_threshold_table_and_extrapolation() -> None:
    assert RULESET.threshold_for_household(1) == 2610
    assert RULESET.threshold_for_household(2) == 3526
    assert RULESET.threshold_for_household(4) == 5360
    assert RULESET.threshold_for_household(8) == 9030
    assert RULESET.threshold_for_household(9) == 9030 + 918
    assert RULESET.threshold_for_household(10) == 9030 + 2 * 918


def test_threshold_rejects_zero_size() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        RULESET.threshold_for_household(0)


def test_likely_eligible_single() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_ELIGIBLE
    assert result.threshold_used == 2610
    assert result.rule_version == RULESET.id
    assert result.household_size == 1


def test_eligible_at_exact_threshold() -> None:
    """At-or-below threshold is likely eligible."""
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2610.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_ELIGIBLE


def test_likely_ineligible_one_dollar_over() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2610.01),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_likely_ineligible_high_income() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(5000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_household_of_four_screen() -> None:
    thr = RULESET.threshold_for_household(4)
    under = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(4),
        normalized_gross_monthly=_known(thr - 1),
    )
    over = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(4),
        normalized_gross_monthly=_known(thr + 1),
    )
    assert calculate_eligibility(under).status == AssessmentStatus.LIKELY_ELIGIBLE
    assert calculate_eligibility(over).status == AssessmentStatus.LIKELY_INELIGIBLE


def test_not_in_nc() -> None:
    case = EligibilityCase(lives_in_nc=_known(False))
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE
    assert "nc-fns-overview" in result.source_ids


def test_missing_residency() -> None:
    case = EligibilityCase()
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "residency" in result.reasons[0].lower()


def test_missing_household_size() -> None:
    case = EligibilityCase(lives_in_nc=_known(True))
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "household" in result.reasons[0].lower()


def test_missing_income() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(2),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "income" in result.reasons[0].lower()


def test_uncertain_income_amount_needs_more_info() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        income_amount=_uncertain(2500.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "approximately" in result.reasons[0].lower() or "clearer" in result.reasons[0].lower()


def test_net_income_unable_to_determine() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        gross_or_net=_known("net"),
        normalized_gross_monthly=_uncertain(2000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert any("net" in r.lower() for r in result.reasons)


def test_individual_income_multi_person_unable() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(3),
        household_or_individual=_known("individual"),
        normalized_gross_monthly=_uncertain(2000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert any("individual" in r.lower() or "household" in r.lower() for r in result.reasons)


def test_student_softens_eligible_to_unable() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
        is_student=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert "nc-fns-student-rules" in result.source_ids


def test_student_ineligible_stays_ineligible() -> None:
    """Student caveat does not override a failed gross screen."""
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(9000.0),
        is_student=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE
    assert "nc-fns-student-rules" in result.source_ids


def test_elderly_adds_caveat_not_status_change() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
        elderly_or_disabled_member=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_ELIGIBLE
    assert any("elderly" in c.lower() or "disabled" in c.lower() for c in result.caveats)


def test_assessment_always_includes_disclaimer_caveats() -> None:
    case = EligibilityCase(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
    )
    result = calculate_eligibility(case)
    assert any("informal" in c.lower() or "not an official" in c.lower() for c in result.caveats)
    assert any(RULESET.id in c for c in result.caveats)
