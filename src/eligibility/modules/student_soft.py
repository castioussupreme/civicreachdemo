"""Optional student softener: income pass → unable without full student rules."""

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
from src.eligibility.thresholds import threshold_for_household
from src.programs.models import ProgramMeta, Ruleset
from src.state.models import EligibilityCase, FieldStatus

_ALLOWED = frozenset({"source_id"})


class StudentSoftUnableModule:
    type_id = "student_soft_unable"

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        reject_unknown_keys(params, _ALLOWED, self.type_id)
        source_id = _as_str(params.get("source_id"), "")
        if not source_id:
            raise ValueError("student_soft_unable: source_id is required")
        return {"source_id": source_id}

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
        ruleset: Ruleset | None = None,
        ruleset_source_id: str = "",
        supporting_source_ids: tuple[str, ...] = (),
    ) -> ModuleResult:
        _ = program, ruleset_source_id, supporting_source_ids
        source_id = _as_str(spec.params.get("source_id"), "")
        sources = [source_id] if source_id else []
        caveats = [
            "College student rules are not fully modeled here. Students often need an "
            "additional exemption beyond the income screen; DSS or campus outreach must decide."
        ]

        if not (case.is_student.is_usable() and case.is_student.value is True):
            return ModuleResult(outcome=ModuleOutcome.PASS)

        under = _gross_would_pass(case, ruleset)
        if under is True:
            return ModuleResult(
                outcome=ModuleOutcome.UNABLE,
                reasons=[
                    "On the simple gross-income table alone this would look like a pass, "
                    "but student-specific rules are not evaluated by this tool — "
                    "so overall we cannot give a confident screening result."
                ],
                source_ids=sources,
                caveats=caveats,
            )
        if under is False:
            return ModuleResult(
                outcome=ModuleOutcome.PASS,
                reasons=[
                    "Student status does not change a failed gross-income screen on this tool."
                ],
                source_ids=sources,
                caveats=caveats,
            )
        return ModuleResult(
            outcome=ModuleOutcome.PASS,
            source_ids=sources,
            caveats=caveats,
        )


def _gross_would_pass(case: EligibilityCase, ruleset: Ruleset | None) -> bool | None:
    if case.normalized_gross_monthly.status != FieldStatus.KNOWN:
        return None
    if case.normalized_gross_monthly.value is None:
        return None
    if not case.household_size.is_usable() or case.household_size.value is None:
        return None
    if ruleset is None:
        return None
    table = ruleset.gross_income_table()
    increment = ruleset.gross_income_increment()
    if table is None or increment is None:
        return None
    thr = threshold_for_household(table, increment, int(case.household_size.value))
    return float(case.normalized_gross_monthly.value) <= thr
