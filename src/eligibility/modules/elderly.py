"""Optional elderly/disabled caveat (never changes status)."""

from __future__ import annotations

from collections.abc import Mapping

from src.eligibility.modules.base import (
    MissingItem,
    ModuleOutcome,
    ModuleResult,
    RequirementSpec,
    reject_unknown_keys,
)
from src.programs.models import ProgramMeta
from src.state.models import EligibilityCase

_ALLOWED: frozenset[str] = frozenset()


class ElderlyDisabledCaveatModule:
    type_id = "elderly_disabled_caveat"

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        reject_unknown_keys(params, _ALLOWED, self.type_id)
        return {}

    def missing(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
    ) -> list[MissingItem]:
        _ = case, spec, program
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
        _ = spec, program, ruleset, ruleset_source_id, supporting_source_ids
        if case.elderly_or_disabled_member.is_usable() and case.elderly_or_disabled_member.value:
            return ModuleResult(
                outcome=ModuleOutcome.PASS,
                caveats=[
                    "Household may include elderly or disabled members; DSS may apply "
                    "different resource or income treatment not modeled here."
                ],
            )
        return ModuleResult(outcome=ModuleOutcome.PASS)
