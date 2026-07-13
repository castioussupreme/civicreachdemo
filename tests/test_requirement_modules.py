"""Requirement modules: declare-driven planner/engine (no LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from src.eligibility.engine import calculate_eligibility
from src.eligibility.modules import get_module, parse_requirements
from src.eligibility.modules.base import ModuleOutcome
from src.eligibility.modules.gross_income import GrossIncomeLimitModule
from src.eligibility.modules.residency import ResidencyModule
from src.eligibility.ruleset import load_ruleset
from src.planner.missing import determine_missing_fields
from src.programs.models import ProgramMeta, Ruleset
from src.state.models import CaseField, EligibilityCase, FieldStatus

T = TypeVar("T")


def _known(value: T) -> CaseField[T]:
    return CaseField(status=FieldStatus.KNOWN, value=value)


def _program() -> ProgramMeta:
    return ProgramMeta(
        slug="fixture",
        display_name="Fixture Program",
        search_aliases=(),
        program_effective_from=None,
        program_effective_to=None,
        opening_message="hi",
        root=Path(),
        service_area_name="Testland",
        service_area_short="Testland",
    )


def _residency_only_ruleset() -> Ruleset:
    specs = parse_requirements([{"type": "residency"}])
    return Ruleset(
        id="fixture-residency-only",
        effective_from="2025-01-01",
        effective_to=None,
        source_id="fixture-source",
        description="residency only",
        program_slug="fixture",
        supporting_source_ids=(),
        requirements=specs,
    )


def test_parse_requirements_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        parse_requirements([])
    with pytest.raises(ValueError, match="required"):
        parse_requirements(None)


def test_parse_requirements_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown requirement type"):
        parse_requirements([{"type": "not_a_real_module"}])


def test_gross_income_rejects_unknown_param() -> None:
    mod = GrossIncomeLimitModule()
    with pytest.raises(ValueError, match="unknown param"):
        mod.validate(
            {
                "max_gross_monthly_by_size": {1: 100.0, 8: 800.0},
                "additional_member_increment": 10,
                "bogus": True,
            }
        )


def test_residency_only_planner_never_asks_income() -> None:
    """Pack without gross_income_limit must not interview for income."""
    rs = _residency_only_ruleset()
    case = EligibilityCase(
        program_slug="fixture",
        ruleset_id=rs.id,
        as_of="2026-03-01",
        ruleset_effective_from=rs.effective_from,
        ruleset_effective_to=rs.effective_to,
    )
    # Inject ruleset resolution by monkeypatching would be heavy; call modules directly.
    program = _program()
    missing_keys: list[str] = []
    for spec in rs.requirements:
        for item in get_module(spec.type).missing(case, spec, program=program):
            missing_keys.append(item.field_key)
    assert missing_keys == ["lives_in_service_area"]
    assert "income_amount" not in missing_keys
    assert "household_size" not in missing_keys

    case.lives_in_service_area = _known(True)
    missing_keys = []
    for spec in rs.requirements:
        for item in get_module(spec.type).missing(case, spec, program=program):
            missing_keys.append(item.field_key)
    assert missing_keys == []

    result = ResidencyModule().assess(
        case,
        rs.requirements[0],
        program=program,
        ruleset_source_id=rs.source_id,
    )
    assert result.outcome == ModuleOutcome.PASS


def test_residency_only_engine_eligible_without_income() -> None:
    rs = _residency_only_ruleset()
    case = EligibilityCase(
        program_slug="fixture",
        ruleset_id=rs.id,
        as_of="2026-03-01",
        ruleset_effective_from=rs.effective_from,
        ruleset_effective_to=rs.effective_to,
        lives_in_service_area=_known(True),
    )
    # calculate_eligibility loads ruleset by id from registry — pass ruleset explicitly
    result = calculate_eligibility(case, ruleset=rs)
    assert result.status.value == "likely_eligible"
    assert result.threshold_used is None


def test_planner_uses_declared_modules_only() -> None:
    """Any pack with residency-first requirements starts by asking residency."""
    rs = load_ruleset("nc-fns")
    case = EligibilityCase(
        program_slug="nc-fns",
        ruleset_id=rs.id,
        as_of="2026-03-01",
        ruleset_effective_from=rs.effective_from,
        ruleset_effective_to=rs.effective_to,
        screening_started=True,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is False
    assert "lives_in_service_area" in plan.missing_fields
