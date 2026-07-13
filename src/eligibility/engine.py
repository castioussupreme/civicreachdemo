"""Eligibility orchestrator: run declared requirement modules only."""

from __future__ import annotations

from pathlib import Path

from src.eligibility.modules import SOFT_MODULE_TYPES, ModuleOutcome, get_module
from src.eligibility.ruleset import Ruleset
from src.programs.models import ProgramMeta
from src.programs.registry import get_program, get_ruleset_by_id
from src.state.models import (
    Assessment,
    AssessmentStatus,
    EligibilityCase,
)


def _ruleset_for_case(case: EligibilityCase, ruleset: Ruleset | None) -> Ruleset:
    if ruleset is not None:
        return ruleset
    slug = (case.program_slug or "").strip()
    rid = (case.ruleset_id or "").strip()
    if not slug or not rid:
        raise ValueError("case.program_slug and case.ruleset_id are required (no default program)")
    return get_ruleset_by_id(slug, rid)


def calculate_eligibility(
    case: EligibilityCase,
    ruleset: Ruleset | None = None,
) -> Assessment:
    """
    Deterministic screening assessment driven by ruleset.requirements.

    Pure function of case state + pinned ruleset modules.
    """
    ruleset = _ruleset_for_case(case, ruleset)
    try:
        program = get_program(ruleset.program_slug or case.program_slug)
    except Exception:
        program = ProgramMeta(
            slug=case.program_slug or "unknown",
            display_name=case.program_slug or "program",
            search_aliases=(),
            program_effective_from=None,
            program_effective_to=None,
            opening_message="",
            root=Path(),
            service_area_name="the program service area",
            service_area_short="this program",
        )

    agency = program.apply_channel or "the agency"
    base_caveats: list[str] = [
        f"This is an informal screening only—not an official determination by {agency}.",
        (
            f"Ruleset {ruleset.id} effective from {ruleset.effective_from}"
            + (f" to {ruleset.effective_to}" if ruleset.effective_to else " (open-ended)")
            + "."
        ),
    ]

    reasons: list[str] = []
    source_ids: list[str] = []
    caveats: list[str] = list(base_caveats)
    threshold_used: float | None = None
    monthly: float | None = None
    household_size: int | None = None

    had_fail = False
    had_unable = False
    unable_reasons: list[str] = []

    for spec in ruleset.requirements:
        if had_fail and spec.type not in SOFT_MODULE_TYPES:
            continue
        module = get_module(spec.type)
        result = module.assess(
            case,
            spec,
            program=program,
            ruleset=ruleset,
            ruleset_source_id=ruleset.source_id,
            supporting_source_ids=ruleset.supporting_source_ids,
        )

        for sid in result.source_ids:
            if sid and sid not in source_ids:
                source_ids.append(sid)
        caveats.extend(result.caveats)
        if result.threshold_used is not None:
            threshold_used = result.threshold_used
        if result.normalized_gross_monthly is not None:
            monthly = result.normalized_gross_monthly
        if result.household_size is not None:
            household_size = result.household_size

        if result.outcome == ModuleOutcome.NEED_MORE:
            return Assessment(
                status=AssessmentStatus.NEEDS_MORE_INFORMATION,
                reasons=list(result.reasons) or ["Need more information to complete screening."],
                rule_version=ruleset.id,
                source_ids=list(dict.fromkeys(source_ids)),
                caveats=list(dict.fromkeys(caveats)),
                threshold_used=threshold_used,
                normalized_gross_monthly=monthly,
                household_size=household_size,
            )

        if result.outcome == ModuleOutcome.FAIL:
            had_fail = True
            reasons.extend(result.reasons)
            continue

        if result.outcome == ModuleOutcome.UNABLE:
            had_unable = True
            unable_reasons.extend(result.reasons)
            reasons.extend(result.reasons)
            continue

        # PASS / SKIP
        reasons.extend(result.reasons)

    if had_fail:
        status = AssessmentStatus.LIKELY_INELIGIBLE
    elif had_unable:
        status = AssessmentStatus.UNABLE_TO_DETERMINE
        if not reasons:
            reasons = unable_reasons or ["Unable to determine from this simple screen."]
    else:
        status = AssessmentStatus.LIKELY_ELIGIBLE
        if not reasons:
            reasons = ["Screening requirements were met for this informal check."]

    return Assessment(
        status=status,
        reasons=list(dict.fromkeys(reasons)),
        rule_version=ruleset.id,
        source_ids=list(dict.fromkeys(source_ids)),
        threshold_used=threshold_used,
        normalized_gross_monthly=monthly,
        household_size=household_size,
        caveats=list(dict.fromkeys(caveats)),
    )
