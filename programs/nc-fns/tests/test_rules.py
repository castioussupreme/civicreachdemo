"""NC FNS rulesets, multi-year pin, and pack metadata."""

from __future__ import annotations

from datetime import date
from typing import TypeVar

import pytest
from src.eligibility.engine import calculate_eligibility
from src.eligibility.ruleset import load_ruleset
from src.programs.registry import (
    ProgramNotAvailableError,
    catalog_programs,
    get_program,
    get_ruleset_by_id,
    resolve_ruleset,
)
from src.state.models import CaseField, FieldStatus, fresh_case

T = TypeVar("T")
RULESET = load_ruleset("nc-fns")


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def test_program_metadata() -> None:
    p = get_program("nc-fns")
    assert "Food" in p.display_name or "FNS" in p.display_name or "SNAP" in p.display_name
    assert p.knowledge_dir.is_dir()
    assert p.rules_dir.is_dir()
    assert p.matches_query("snap")
    assert p.matches_query("food")
    assert "North Carolina" in p.service_area_name or "Carolina" in p.service_area_name


def test_requirements_include_gross_and_student() -> None:
    types = [r.type for r in RULESET.requirements]
    assert types[0] == "residency"
    assert "gross_income_limit" in types
    assert "student_soft_unable" in types
    assert RULESET.gross_income_table() is not None
    assert RULESET.threshold_for_household(2) == 3526.0


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


def test_resolve_ruleset_current_fy() -> None:
    rs = resolve_ruleset("nc-fns", date(2026, 3, 1))
    assert rs.id == "nc-fns-screening-2025-10"
    assert rs.threshold_for_household(2) == 3526.0
    assert rs.covers(date(2026, 3, 1))
    assert not rs.covers(date(2024, 1, 1))


def test_resolve_ruleset_prior_fy() -> None:
    rs = resolve_ruleset("nc-fns", date(2025, 3, 1))
    assert rs.id == "nc-fns-screening-2024-10"
    assert rs.threshold_for_household(2) == 3408.0
    assert rs.covers(date(2025, 9, 30))
    assert not rs.covers(date(2025, 10, 1))


def test_resolve_ruleset_last_day_of_prior_fy() -> None:
    rs = resolve_ruleset("nc-fns", date(2025, 9, 30))
    assert rs.id == "nc-fns-screening-2024-10"
    assert rs.threshold_for_household(2) == 3408.0


def test_resolve_ruleset_outside_window() -> None:
    with pytest.raises(ProgramNotAvailableError):
        resolve_ruleset("nc-fns", date(2023, 1, 1))


def test_catalog_lists_active_ruleset_for_as_of() -> None:
    prior = catalog_programs(q="nc-fns", as_of=date(2025, 3, 1), limit=10)
    assert prior and prior[0].ruleset_id == "nc-fns-screening-2024-10"
    current = catalog_programs(q="nc-fns", as_of=date(2026, 1, 15), limit=10)
    assert current and current[0].ruleset_id == "nc-fns-screening-2025-10"


def test_fresh_case_pins_ruleset_for_as_of() -> None:
    case = fresh_case(program_slug="nc-fns", as_of="2026-03-01")
    assert case.ruleset_id == "nc-fns-screening-2025-10"
    assert case.ruleset_effective_from == "2025-10-01"
    assert case.ruleset_effective_to == "2026-09-30"

    case_prior = fresh_case(program_slug="nc-fns", as_of="2025-03-01")
    assert case_prior.ruleset_id == "nc-fns-screening-2024-10"
    assert case_prior.ruleset_effective_to == "2025-09-30"


def test_pinned_ruleset_not_re_resolved_when_clock_moves() -> None:
    case = fresh_case(program_slug="nc-fns", as_of="2025-09-30")
    assert case.ruleset_id == "nc-fns-screening-2024-10"
    pinned = get_ruleset_by_id(case.program_slug, case.ruleset_id)
    assert pinned.threshold_for_household(2) == 3408.0
    current = resolve_ruleset(case.program_slug, date(2025, 10, 15))
    assert current.id == "nc-fns-screening-2025-10"
    assert current.threshold_for_household(2) == 3526.0
    case.lives_in_service_area = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3450.0)
    result = calculate_eligibility(case)
    assert result.threshold_used == 3408.0
    assert result.status.value == "likely_ineligible"
    assert result.rule_version == "nc-fns-screening-2024-10"


def test_new_session_after_rollover_uses_new_ruleset() -> None:
    case = fresh_case(program_slug="nc-fns", as_of="2025-10-01")
    case.lives_in_service_area = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3450.0)
    result = calculate_eligibility(case)
    assert result.threshold_used == 3526.0
    assert result.status.value == "likely_eligible"
    assert result.rule_version == "nc-fns-screening-2025-10"
