from __future__ import annotations

from dataclasses import dataclass

from src.eligibility.income import normalize_to_monthly
from src.eligibility.ruleset import RULESET
from src.state.models import EligibilityCase, FieldStatus, Stage


@dataclass(frozen=True)
class PlanResult:
    missing_fields: list[str]
    stage: Stage
    next_question_hint: str
    ready_to_assess: bool
    open_contradictions: list[str]


# Household wording should stay aligned with knowledge/nc-fns-general-requirements.md
# ("buy and prepare food together"). See AGENTS.md.
QUESTION_HINTS = {
    "lives_in_nc": "Do you currently live in North Carolina?",
    "household_size": (
        "How many people buy and prepare food together with you (including yourself)?"
    ),
    "income_amount": (
        "About how much income does your household get before taxes? "
        "A round number is fine — per day, weekly, every two weeks, twice a month, "
        "monthly, or yearly."
    ),
    "income_amount_clarify": (
        "I want to make sure I have the right income figure. "
        "About how much is it, and is that per day, weekly, every two weeks, "
        "twice a month, monthly, or yearly?"
    ),
    "income_period": (
        "Is that amount per day, weekly, every two weeks, twice a month "
        "(like the 1st and 15th), monthly, or yearly?"
    ),
    "gross_or_net": ("Is that roughly before taxes, or take-home pay after taxes?"),
    "household_or_individual": (
        "Is that the total for everyone in the household, or just your income?"
    ),
    "approx_gross": (
        "This screen uses income before taxes (gross), not take-home pay. "
        "About how much is that amount before taxes, if you know? "
        "A rough number is fine — or say if you only know take-home."
    ),
    "approx_household_total": (
        "This screen needs total household income for everyone who buys and prepares "
        "food together — not just one person's pay. "
        "About how much is the household total before taxes, if you know? "
        "A rough number is fine — or say if you only know your own."
    ),
}

FIELD_LABELS = {
    "lives_in_nc": "whether you live in North Carolina",
    "household_size": "household size",
    "income_amount": "income amount",
    "income_period": "how often that income is paid",
    "gross_or_net": "whether income is before or after taxes",
    "household_or_individual": "whether income is household-total or just yours",
    "is_student": "student status",
    "elderly_or_disabled_member": "whether someone is elderly or disabled",
}


def _conflict_question(case: EligibilityCase, field: str) -> str:
    label = FIELD_LABELS.get(field, field.replace("_", " "))
    open_c = next((c for c in case.contradictions if c.field == field and not c.resolved), None)
    if open_c is not None:
        return (
            f"I want to make sure I have this right about {label}. "
            f"Earlier it sounded like {open_c.previous_value!s}, "
            f"and later like {open_c.proposed_value!s}. "
            f"Which should I use?"
        )
    return f"I noticed a possible change about {label}. Which value should I use going forward?"


def _stated_monthly(case: EligibilityCase) -> float | None:
    """Monthly figure from amount+period (gross or take-home — whatever they stated)."""
    if not case.income_amount.is_usable() or not case.income_period.is_usable():
        return None
    amount = case.income_amount.value
    period = case.income_period.value
    if amount is None or period is None:
        return None
    return normalize_to_monthly(float(amount), period)


def _threshold(case: EligibilityCase) -> float | None:
    if not case.household_size.is_usable() or case.household_size.value is None:
        return None
    return RULESET.threshold_for_household(int(case.household_size.value))


def _stated_monthly_exceeds_threshold(case: EligibilityCase) -> bool:
    monthly = _stated_monthly(case)
    thr = _threshold(case)
    if monthly is None or thr is None:
        return False
    return monthly > thr


def _is_net(case: EligibilityCase) -> bool:
    return case.gross_or_net.is_usable() and case.gross_or_net.value == "net"


def _is_individual_multi(case: EligibilityCase) -> bool:
    if not case.household_or_individual.is_usable():
        return False
    if case.household_or_individual.value != "individual":
        return False
    if not case.household_size.is_usable() or case.household_size.value is None:
        return False
    return int(case.household_size.value) > 1


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

    missing: list[str] = []
    hint_overrides: dict[str, str] = {}

    if case.lives_in_nc.status in (FieldStatus.UNKNOWN, FieldStatus.UNCERTAIN):
        missing.append("lives_in_nc")
        if case.lives_in_nc.status == FieldStatus.UNCERTAIN:
            hint_overrides["lives_in_nc"] = (
                "Just to confirm — do you currently live in North Carolina?"
            )
    elif case.lives_in_nc.is_usable() and case.lives_in_nc.value is False:
        return PlanResult(
            missing_fields=[],
            stage=Stage.READY_TO_ASSESS,
            next_question_hint="",
            ready_to_assess=True,
            open_contradictions=[],
        )

    if case.household_size.status in (FieldStatus.UNKNOWN, FieldStatus.UNCERTAIN):
        missing.append("household_size")
        if case.household_size.status == FieldStatus.UNCERTAIN:
            hint_overrides["household_size"] = (
                "About how many people buy and prepare food together with you "
                "(including yourself)? A clear number helps."
            )

    if case.income_amount.status == FieldStatus.UNKNOWN:
        missing.append("income_amount")
    elif case.income_amount.status == FieldStatus.UNCERTAIN:
        # Approximate ("about $2,500") — clarify, don't treat as ready
        missing.append("income_amount_clarify")

    if case.income_amount.is_usable() and case.income_period.status in (
        FieldStatus.UNKNOWN,
        FieldStatus.UNCERTAIN,
    ):
        missing.append("income_period")

    if case.income_amount.is_usable() and case.gross_or_net.status == FieldStatus.UNKNOWN:
        missing.append("gross_or_net")

    if (
        case.household_size.is_usable()
        and case.household_size.value is not None
        and int(case.household_size.value) > 1
        and case.income_amount.is_usable()
        and case.household_or_individual.status == FieldStatus.UNKNOWN
    ):
        missing.append("household_or_individual")

    # --- One-shot follow-ups when income is incomplete (no invented math) ---
    # Order: pre-tax first, then household total. Skip follow-up if stated
    # amount alone already exceeds the gross threshold (safe lower bound).
    base_complete = not missing
    uncertain_norm = case.normalized_gross_monthly.status == FieldStatus.UNCERTAIN
    exceeds = _stated_monthly_exceeds_threshold(case)

    if base_complete and uncertain_norm and not exceeds:
        if _is_net(case) and not case.asked_for_gross_amount:
            missing.append("approx_gross")
        elif _is_individual_multi(case) and not case.asked_for_household_total:
            missing.append("approx_household_total")

    income_ready = case.normalized_gross_monthly.status == FieldStatus.KNOWN

    if missing:
        primary = missing[0]
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

        hint = hint_overrides.get(primary) or QUESTION_HINTS.get(primary, "Could you tell me more?")
        return PlanResult(
            missing_fields=missing,
            stage=stage,
            next_question_hint=hint,
            ready_to_assess=False,
            open_contradictions=[],
        )

    if not income_ready:
        return PlanResult(
            missing_fields=[],
            stage=Stage.READY_TO_ASSESS,
            next_question_hint="",
            ready_to_assess=True,
            open_contradictions=[],
        )

    return PlanResult(
        missing_fields=[],
        stage=Stage.READY_TO_ASSESS,
        next_question_hint="",
        ready_to_assess=True,
        open_contradictions=[],
    )
