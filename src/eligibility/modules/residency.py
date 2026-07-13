"""Residency / service-area hard gate."""

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
from src.state.models import EligibilityCase, FieldStatus

_ALLOWED: frozenset[str] = frozenset()


class ResidencyModule:
    type_id = "residency"

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
        _ = spec
        area = program.service_area_name or "the program service area"
        if case.lives_in_service_area.status == FieldStatus.UNKNOWN:
            return [
                MissingItem(
                    field_key="lives_in_service_area",
                    question_hint=f"Do you currently live in {area}?",
                )
            ]
        if case.lives_in_service_area.status == FieldStatus.UNCERTAIN:
            return [
                MissingItem(
                    field_key="lives_in_service_area",
                    question_hint=f"Just to confirm — do you currently live in {area}?",
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
        _ = spec, ruleset
        area = program.service_area_name or "the program service area"
        name = program.display_name or "this program"
        overview = next(
            (s for s in supporting_source_ids if "overview" in s),
            supporting_source_ids[0] if supporting_source_ids else ruleset_source_id,
        )
        base_sources = [s for s in (ruleset_source_id, *supporting_source_ids) if s]

        if (
            case.lives_in_service_area.status == FieldStatus.KNOWN
            and case.lives_in_service_area.value is False
        ):
            sources = list(dict.fromkeys([*base_sources, overview] if overview else base_sources))
            return ModuleResult(
                outcome=ModuleOutcome.FAIL,
                reasons=[
                    f"User indicated they do not live in {area}; {name} is for {area} residents."
                ],
                source_ids=sources,
                caveats=["Other jurisdictions administer their own assistance programs."],
            )

        if not case.lives_in_service_area.is_usable():
            return ModuleResult(
                outcome=ModuleOutcome.NEED_MORE,
                reasons=[f"{area} residency has not been confirmed."],
                source_ids=base_sources,
            )

        return ModuleResult(outcome=ModuleOutcome.PASS, source_ids=base_sources)
