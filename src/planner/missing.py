from __future__ import annotations

from dataclasses import dataclass

from src.state.models import EligibilityCase, FieldStatus, Stage


@dataclass(frozen=True)
class PlanResult:
    missing_fields: list[str]
    stage: Stage
    next_question_hint: str
    ready_to_assess: bool
    open_contradictions: list[str]


# Priority order for collection
FIELD_PRIORITY = [
    "lives_in_nc",
    "household_size",
    "income_amount",
    "income_period",
    "gross_or_net",
    "household_or_individual",
]

QUESTION_HINTS = {
    "lives_in_nc": "Do you currently live in North Carolina?",
    "household_size": (
        "How many people are in your household who buy and prepare food together (including you)?"
    ),
    "income_amount": (
        "About how much income does your household receive before taxes? "
        "You can give a number and say if it is weekly, biweekly, monthly, or yearly."
    ),
    "income_period": (
        "Is that income amount weekly, every two weeks (biweekly), monthly, or yearly?"
    ),
    "gross_or_net": ("Is that amount roughly before taxes (gross) or after taxes (net/take-home)?"),
    "household_or_individual": (
        "Is that the total income for everyone in the household, or just your own income?"
    ),
    "confirm_conflict": (
        "I noticed a possible change from something you said earlier. "
        "Which value should I use going forward?"
    ),
}


def determine_missing_fields(case: EligibilityCase) -> PlanResult:
    open_conflicts = [c.field for c in case.contradictions if not c.resolved]
    if open_conflicts:
        return PlanResult(
            missing_fields=["confirm_conflict:" + open_conflicts[0]],
            stage=Stage.CLARIFYING,
            next_question_hint=QUESTION_HINTS["confirm_conflict"]
            + f" (field: {open_conflicts[0]})",
            ready_to_assess=False,
            open_contradictions=open_conflicts,
        )

    missing: list[str] = []

    if case.lives_in_nc.status in (FieldStatus.UNKNOWN, FieldStatus.UNCERTAIN):
        missing.append("lives_in_nc")
    elif case.lives_in_nc.is_usable() and case.lives_in_nc.value is False:
        # Can assess ineligible without more fields
        return PlanResult(
            missing_fields=[],
            stage=Stage.READY_TO_ASSESS,
            next_question_hint="",
            ready_to_assess=True,
            open_contradictions=[],
        )

    if case.household_size.status in (FieldStatus.UNKNOWN, FieldStatus.UNCERTAIN):
        missing.append("household_size")

    if case.income_amount.status in (FieldStatus.UNKNOWN, FieldStatus.UNCERTAIN):
        missing.append("income_amount")
    if case.income_amount.is_usable() and case.income_period.status in (
        FieldStatus.UNKNOWN,
        FieldStatus.UNCERTAIN,
    ):
        missing.append("income_period")

    # Ask gross vs net only if income given and not yet known
    if case.income_amount.is_usable() and case.gross_or_net.status == FieldStatus.UNKNOWN:
        missing.append("gross_or_net")

    # Household vs individual if multi-person household
    if (
        case.household_size.is_usable()
        and int(case.household_size.value) > 1  # type: ignore[arg-type]
        and case.income_amount.is_usable()
        and case.household_or_individual.status == FieldStatus.UNKNOWN
    ):
        missing.append("household_or_individual")

    # Normalized income must be usable for assess
    income_ready = case.normalized_gross_monthly.status == FieldStatus.KNOWN

    if missing:
        primary = missing[0]
        stage = Stage.INTRODUCTION if case.turn_count <= 1 else Stage.COLLECTING
        if any(
            getattr(case, f).status == FieldStatus.UNCERTAIN
            for f in (
                "income_amount",
                "income_period",
                "household_size",
                "lives_in_nc",
            )
            if hasattr(case, f)
        ):
            stage = Stage.CLARIFYING
        return PlanResult(
            missing_fields=missing,
            stage=stage,
            next_question_hint=QUESTION_HINTS.get(primary, "Could you tell me more?"),
            ready_to_assess=False,
            open_contradictions=[],
        )

    if not income_ready:
        # All slots present but income uncertain (net/individual)
        return PlanResult(
            missing_fields=[],
            stage=Stage.READY_TO_ASSESS,
            next_question_hint="",
            ready_to_assess=True,  # engine will return unable_to_determine
            open_contradictions=[],
        )

    return PlanResult(
        missing_fields=[],
        stage=Stage.READY_TO_ASSESS,
        next_question_hint="",
        ready_to_assess=True,
        open_contradictions=[],
    )
