"""NC FNS screening engine behavior against this pack's ruleset (no LLM)."""

from __future__ import annotations

from typing import TypeVar

from src.eligibility.engine import calculate_eligibility
from src.eligibility.ruleset import load_ruleset
from src.state.models import AssessmentStatus, CaseField, EligibilityCase, FieldStatus

RULESET = load_ruleset("nc-fns")
T = TypeVar("T")


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def _uncertain(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.UNCERTAIN, value=value)


def _base_case(**kwargs: object) -> EligibilityCase:
    data: dict[str, object] = {
        "program_slug": "nc-fns",
        "ruleset_id": RULESET.id,
        "as_of": "2026-03-01",
        "ruleset_effective_from": RULESET.effective_from,
        "ruleset_effective_to": RULESET.effective_to,
    }
    data.update(kwargs)
    return EligibilityCase(**data)  # type: ignore[arg-type]


def test_likely_eligible_single() -> None:
    case = _base_case(
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
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2610.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_ELIGIBLE


def test_likely_ineligible_one_dollar_over() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2610.01),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_likely_ineligible_high_income() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(5000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_household_of_four_screen() -> None:
    thr = RULESET.threshold_for_household(4)
    under = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(4),
        normalized_gross_monthly=_known(thr - 1),
    )
    over = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(4),
        normalized_gross_monthly=_known(thr + 1),
    )
    assert calculate_eligibility(under).status == AssessmentStatus.LIKELY_ELIGIBLE
    assert calculate_eligibility(over).status == AssessmentStatus.LIKELY_INELIGIBLE
    assert "nc-fns-gross-income-tests" in calculate_eligibility(under).source_ids
    assert "nc-fns-income-limits" in calculate_eligibility(under).source_ids


def test_not_in_service_area() -> None:
    case = _base_case(lives_in_nc=_known(False))
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE
    assert "nc-fns-overview" in result.source_ids


def test_missing_residency() -> None:
    case = _base_case()
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "residency" in result.reasons[0].lower()


def test_missing_household_size() -> None:
    case = _base_case(lives_in_nc=_known(True))
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "household" in result.reasons[0].lower()


def test_missing_income() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(2),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "income" in result.reasons[0].lower()


def test_uncertain_income_amount_needs_more_info() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        income_amount=_uncertain(2500.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.NEEDS_MORE_INFORMATION
    assert "approximately" in result.reasons[0].lower() or "clearer" in result.reasons[0].lower()


def test_net_income_unable_to_determine_when_under_threshold() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        gross_or_net=_known("net"),
        normalized_gross_monthly=_uncertain(2000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert any("take-home" in r.lower() or "after tax" in r.lower() for r in result.reasons)


def test_net_takehome_above_threshold_likely_ineligible() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        gross_or_net=_known("net"),
        normalized_gross_monthly=_uncertain(9000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE
    assert result.threshold_used == 2610


def test_individual_income_multi_person_unable_when_under_threshold() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(3),
        household_or_individual=_known("individual"),
        normalized_gross_monthly=_uncertain(2000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE


def test_individual_income_above_threshold_likely_ineligible() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(3),
        household_or_individual=_known("individual"),
        normalized_gross_monthly=_uncertain(9000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_net_and_individual_above_threshold() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(4),
        gross_or_net=_known("net"),
        household_or_individual=_known("individual"),
        normalized_gross_monthly=_uncertain(8000.0),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE


def test_student_softens_eligible_to_unable() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
        is_student=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert "nc-fns-student-rules" in result.source_ids


def test_student_ineligible_stays_ineligible() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(9000.0),
        is_student=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_INELIGIBLE
    assert "nc-fns-student-rules" in result.source_ids


def test_elderly_adds_caveat_not_status_change() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
        elderly_or_disabled_member=_known(True),
    )
    result = calculate_eligibility(case)
    assert result.status == AssessmentStatus.LIKELY_ELIGIBLE
    assert any("elderly" in c.lower() or "disabled" in c.lower() for c in result.caveats)


def test_assessment_always_includes_disclaimer_caveats() -> None:
    case = _base_case(
        lives_in_nc=_known(True),
        household_size=_known(1),
        normalized_gross_monthly=_known(2000.0),
    )
    result = calculate_eligibility(case)
    assert any("informal" in c.lower() or "not an official" in c.lower() for c in result.caveats)
    assert any(RULESET.id in c for c in result.caveats)
