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
    case = fresh_case(as_of="2026-03-01")
    assert case.ruleset_id == "nc-fns-screening-2025-10"
    assert case.ruleset_effective_from == "2025-10-01"
    assert case.ruleset_effective_to == "2026-09-30"

    case_next = fresh_case(as_of="2026-10-15")
    assert case_next.ruleset_id == "nc-fns-screening-2026-10"
    assert case_next.ruleset_effective_to is None


def test_pinned_ruleset_not_re_resolved_when_clock_moves() -> None:
    """
    Case created before FY boundary keeps its ruleset even if we would resolve
    a newer one for 'today' after the boundary.
    """
    case = fresh_case(as_of="2026-09-30")
    assert case.ruleset_id == "nc-fns-screening-2025-10"
    # Simulate wall clock past rollover — pinned id must still load 2025 table
    pinned = get_ruleset_by_id(case.program_slug, case.ruleset_id)
    assert pinned.threshold_for_household(2) == 3526.0
    current = resolve_ruleset(case.program_slug, date(2026, 10, 15))
    assert current.id == "nc-fns-screening-2026-10"
    assert current.threshold_for_household(2) == 3600.0
    # Engine uses pinned ruleset from case, not resolve(today)
    case.lives_in_nc = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3550.0)  # under 3600, over 3526
    result = calculate_eligibility(case)
    assert result.threshold_used == 3526.0
    assert result.status.value == "likely_ineligible"
    assert result.rule_version == "nc-fns-screening-2025-10"


def test_new_session_after_rollover_uses_new_ruleset() -> None:
    case = fresh_case(as_of="2026-10-01")
    case.lives_in_nc = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3550.0)  # under new 3600
    result = calculate_eligibility(case)
    assert result.threshold_used == 3600.0
    assert result.status.value == "likely_eligible"
    assert result.rule_version == "nc-fns-screening-2026-10"
