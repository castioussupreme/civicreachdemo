"""Household size requirement."""

from __future__ import annotations

from collections.abc import Mapping

from src.eligibility.modules.base import (
    MissingItem,
    ModuleOutcome,
    ModuleResult,
    RequirementSpec,
    _as_str,
    reject_unknown_keys,
)
from src.programs.models import ProgramMeta
from src.state.models import EligibilityCase, FieldStatus

_ALLOWED = frozenset({"household_definition"})


def _household_question(definition: str, *, clarify: bool = False) -> str:
    if definition == "buy_and_prepare_food":
        core = "How many people buy and prepare food together with you (including yourself)?"
        if clarify:
            return (
                "About how many people buy and prepare food together with you "
                "(including yourself)? A clear number helps."
            )
        return core
    core = "How many people are in your household (including yourself)?"
    if clarify:
        return "About how many people are in your household (including yourself)? A clear number helps."
    return core


class HouseholdSizeModule:
    type_id = "household_size"

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        reject_unknown_keys(params, _ALLOWED, self.type_id)
        definition = _as_str(params.get("household_definition"), "generic") or "generic"
        return {"household_definition": definition}

    def missing(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
    ) -> list[MissingItem]:
        _ = program
        definition = _as_str(spec.params.get("household_definition"), "generic")
        if case.household_size.status == FieldStatus.UNKNOWN:
            return [
                MissingItem(
                    field_key="household_size",
                    question_hint=_household_question(definition),
                )
            ]
        if case.household_size.status == FieldStatus.UNCERTAIN:
            return [
                MissingItem(
                    field_key="household_size",
                    question_hint=_household_question(definition, clarify=True),
                )
            ]
        return []

    def assess(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
        ruleset: object = None,
        ruleset_source_id: str = "",
        supporting_source_ids: tuple[str, ...] = (),
    ) -> ModuleResult:
        _ = spec, program, ruleset, supporting_source_ids
        base_sources = [s for s in (ruleset_source_id,) if s]
        if not case.household_size.is_usable() or case.household_size.value is None:
            return ModuleResult(
                outcome=ModuleOutcome.NEED_MORE,
                reasons=["Household size is missing or not confirmed."],
                source_ids=base_sources,
            )
        size = int(case.household_size.value)
        return ModuleResult(
            outcome=ModuleOutcome.PASS,
            household_size=size,
            source_ids=base_sources,
        )
