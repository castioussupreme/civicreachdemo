"""Pinned ruleset on session stays stable (no silent mid-session FY flip)."""

from __future__ import annotations

from datetime import date
from typing import TypeVar

from src.eligibility.engine import calculate_eligibility
from src.programs.registry import get_ruleset_by_id, resolve_ruleset
from src.state.models import CaseField, FieldStatus, fresh_case

T = TypeVar("T")


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def test_fresh_case_pins_ruleset_for_as_of() -> None:
    # During current FFY 2026 table window
    case = fresh_case(as_of="2026-03-01")
    assert case.ruleset_id == "nc-fns-screening-2025-10"
    assert case.ruleset_effective_from == "2025-10-01"
    assert case.ruleset_effective_to == "2026-09-30"

    # Prior FFY
    case_prior = fresh_case(as_of="2025-03-01")
    assert case_prior.ruleset_id == "nc-fns-screening-2024-10"
    assert case_prior.ruleset_effective_to == "2025-09-30"


def test_pinned_ruleset_not_re_resolved_when_clock_moves() -> None:
    """
    Case created on last day of prior FY keeps 2024-10 table even after
    resolve(today) would pick 2025-10.
    """
    case = fresh_case(as_of="2025-09-30")
    assert case.ruleset_id == "nc-fns-screening-2024-10"
    pinned = get_ruleset_by_id(case.program_slug, case.ruleset_id)
    assert pinned.threshold_for_household(2) == 3408.0
    current = resolve_ruleset(case.program_slug, date(2025, 10, 15))
    assert current.id == "nc-fns-screening-2025-10"
    assert current.threshold_for_household(2) == 3526.0
    # 3450 is over prior-year limit (3408) but under current (3526)
    case.lives_in_nc = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3450.0)
    result = calculate_eligibility(case)
    assert result.threshold_used == 3408.0
    assert result.status.value == "likely_ineligible"
    assert result.rule_version == "nc-fns-screening-2024-10"


def test_new_session_after_rollover_uses_new_ruleset() -> None:
    case = fresh_case(as_of="2025-10-01")
    case.lives_in_nc = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3450.0)  # under new 3526
    result = calculate_eligibility(case)
    assert result.threshold_used == 3526.0
    assert result.status.value == "likely_eligible"
    assert result.rule_version == "nc-fns-screening-2025-10"
