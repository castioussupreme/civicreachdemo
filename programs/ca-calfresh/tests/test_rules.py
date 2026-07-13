"""CalFresh ruleset, requirements, and pack metadata."""

from __future__ import annotations

from datetime import date
from typing import TypeVar

from src.eligibility.engine import calculate_eligibility
from src.eligibility.ruleset import load_ruleset
from src.programs.registry import get_program, resolve_ruleset
from src.state.models import CaseField, FieldStatus, fresh_case

T = TypeVar("T")
RULESET = load_ruleset("ca-calfresh", as_of=date(2026, 3, 1))


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def test_program_metadata() -> None:
    p = get_program("ca-calfresh")
    assert "CalFresh" in p.display_name or "calfresh" in p.display_name.lower()
    assert p.knowledge_dir.is_dir()
    assert p.rules_dir.is_dir()
    assert p.matches_query("calfresh") or p.matches_query("california")
    assert "California" in p.service_area_name


def test_requirements_no_student_module() -> None:
    types = [r.type for r in RULESET.requirements]
    assert "residency" in types
    assert "gross_income_limit" in types
    assert "student_soft_unable" not in types


def test_threshold_table() -> None:
    assert RULESET.id == "ca-calfresh-screening-2025-10"
    assert RULESET.threshold_for_household(1) == 2610.0
    assert RULESET.threshold_for_household(2) == 3526.0
    assert RULESET.threshold_for_household(6) == 7192.0
    assert RULESET.threshold_for_household(8) == 9026.0
    assert RULESET.threshold_for_household(9) == 9026.0 + 918.0


def test_resolve_ruleset_current() -> None:
    rs = resolve_ruleset("ca-calfresh", date(2026, 3, 1))
    assert rs.id == "ca-calfresh-screening-2025-10"
    assert rs.source_id == "calfresh-income-limits"


def test_session_uses_calfresh_sources() -> None:
    case = fresh_case(program_slug="ca-calfresh", as_of="2026-03-01")
    assert case.program_slug == "ca-calfresh"
    assert case.ruleset_id == "ca-calfresh-screening-2025-10"
    case.lives_in_service_area = _known(True)
    case.household_size = _known(2)
    case.normalized_gross_monthly = _known(3000.0)
    result = calculate_eligibility(case)
    assert result.threshold_used == 3526.0
    assert result.status.value == "likely_eligible"
    assert "calfresh-income-limits" in result.source_ids
    assert "nc-fns-income-limits" not in result.source_ids


def test_not_in_service_area_message() -> None:
    case = fresh_case(program_slug="ca-calfresh", as_of="2026-03-01")
    case.lives_in_service_area = _known(False)
    result = calculate_eligibility(case)
    assert result.status.value == "likely_ineligible"
    assert "California" in result.reasons[0]
