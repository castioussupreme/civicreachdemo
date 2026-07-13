"""Planner: collect missing fields from declared requirement modules only."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from src.eligibility.modules import get_module
from src.programs.registry import get_program, get_ruleset_by_id
from src.state.models import EligibilityCase, FieldStatus, Stage


@dataclass(frozen=True)
class PlanResult:
    missing_fields: list[str]
    stage: Stage
    next_question_hint: str
    ready_to_assess: bool
    open_contradictions: list[str]


def _field_labels(case: EligibilityCase) -> dict[str, str]:
    area = "the program service area"
    slug = (case.program_slug or "").strip()
    if slug:
        with suppress(Exception):
            area = get_program(slug).service_area_name or area
    return {
        "lives_in_nc": f"whether you live in {area}",
        "household_size": "household size",
        "income_amount": "income amount",
        "income_period": "how often that income is paid",
        "gross_or_net": "whether income is before or after taxes",
        "household_or_individual": "whether income is household-total or just yours",
        "is_student": "student status",
        "elderly_or_disabled_member": "whether someone is elderly or disabled",
    }


def _conflict_question(case: EligibilityCase, field: str) -> str:
    label = _field_labels(case).get(field, field.replace("_", " "))
    open_c = next((c for c in case.contradictions if c.field == field and not c.resolved), None)
    if open_c is not None:
        return (
            f"I want to make sure I have this right about {label}. "
            f"Earlier it sounded like {open_c.previous_value!s}, "
            f"and later like {open_c.proposed_value!s}. "
            f"Which should I use?"
        )
    return f"I noticed a possible change about {label}. Which value should I use going forward?"


def determine_missing_fields(case: EligibilityCase) -> PlanResult:
    open_conflicts = [c.field for c in case.contradictions if not c.resolved]
    if open_conflicts:
        field = open_conflicts[0]
        return PlanResult(
            missing_fields=["confirm_conflict:" + field],
            stage=Stage.CLARIFYING,
            next_question_hint=_conflict_question(case, field),
            ready_to_assess=False,
            open_contradictions=open_conflicts,
        )

    slug = (case.program_slug or "").strip()
    rid = (case.ruleset_id or "").strip()
    if not slug or not rid:
        return PlanResult(
            missing_fields=["program"],
            stage=Stage.CLARIFYING,
            next_question_hint="I need a program selected before we can continue.",
            ready_to_assess=False,
            open_contradictions=[],
        )

    try:
        ruleset = get_ruleset_by_id(slug, rid)
        program = get_program(slug)
    except Exception:
        return PlanResult(
            missing_fields=["program"],
            stage=Stage.CLARIFYING,
            next_question_hint="I could not load this program's rules. Please start a new session.",
            ready_to_assess=False,
            open_contradictions=[],
        )

    # Residency hard-fail: assess without collecting further fields.
    if case.lives_in_nc.is_usable() and case.lives_in_nc.value is False:
        return PlanResult(
            missing_fields=[],
            stage=Stage.READY_TO_ASSESS,
            next_question_hint="",
            ready_to_assess=True,
            open_contradictions=[],
        )

    missing_keys: list[str] = []
    hints: dict[str, str] = {}
    for spec in ruleset.requirements:
        module = get_module(spec.type)
        for item in module.missing(case, spec, program=program):
            if item.field_key not in missing_keys:
                missing_keys.append(item.field_key)
                hints[item.field_key] = item.question_hint

    if missing_keys:
        primary = missing_keys[0]
        stage = Stage.INTRODUCTION if case.turn_count <= 1 else Stage.COLLECTING
        clarifying_keys = {
            "approx_gross",
            "approx_household_total",
            "income_amount_clarify",
            "confirm_conflict",
        }
        if (
            primary in clarifying_keys
            or primary.startswith("confirm_conflict")
            or any(
                getattr(case, f).status == FieldStatus.UNCERTAIN
                for f in (
                    "income_amount",
                    "income_period",
                    "household_size",
                    "lives_in_nc",
                )
                if hasattr(case, f)
            )
        ):
            stage = Stage.CLARIFYING

        return PlanResult(
            missing_fields=missing_keys,
            stage=stage,
            next_question_hint=hints.get(primary, "Could you tell me more?"),
            ready_to_assess=False,
            open_contradictions=[],
        )

    return PlanResult(
        missing_fields=[],
        stage=Stage.READY_TO_ASSESS,
        next_question_hint="",
        ready_to_assess=True,
        open_contradictions=[],
    )
