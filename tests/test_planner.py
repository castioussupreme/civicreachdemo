"""Missing-field planner (deterministic, no LLM)."""

from __future__ import annotations

from src.planner.missing import determine_missing_fields
from src.state.models import CaseField, Contradiction, EligibilityCase, FieldStatus, Stage


def test_starts_with_residency() -> None:
    plan = determine_missing_fields(EligibilityCase())
    assert plan.missing_fields[0] == "lives_in_nc"
    assert plan.ready_to_assess is False
    assert plan.stage == Stage.INTRODUCTION


def test_not_in_nc_ready_to_assess() -> None:
    case = EligibilityCase(lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=False))
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is True
    assert plan.missing_fields == []
    assert plan.stage == Stage.READY_TO_ASSESS


def test_collects_household_then_income() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        turn_count=2,
    )
    plan = determine_missing_fields(case)
    assert plan.missing_fields[0] == "household_size"
    assert plan.stage == Stage.COLLECTING

    case.household_size = CaseField(status=FieldStatus.KNOWN, value=2)
    plan = determine_missing_fields(case)
    assert "income_amount" in plan.missing_fields


def test_asks_period_and_gross_after_amount() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        turn_count=3,
    )
    plan = determine_missing_fields(case)
    assert "income_period" in plan.missing_fields
    assert "gross_or_net" in plan.missing_fields


def test_asks_household_vs_individual_for_multi_person() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=3),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="gross"),
        turn_count=4,
    )
    plan = determine_missing_fields(case)
    assert plan.missing_fields[0] == "household_or_individual"
    assert plan.ready_to_assess is False


def test_skips_household_or_individual_for_single() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="gross"),
        normalized_gross_monthly=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        turn_count=4,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is True
    assert "household_or_individual" not in plan.missing_fields


def test_net_income_asks_for_approx_gross_once() -> None:
    """Take-home under the gross limit → ask for pre-tax; do not invent tax math."""
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="net"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=2000.0),
        turn_count=5,
        asked_for_gross_amount=False,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is False
    assert "approx_gross" in plan.missing_fields
    assert (
        "before tax" in plan.next_question_hint.lower()
        or "gross" in plan.next_question_hint.lower()
    )


def test_net_income_after_gross_followup_ready_to_assess() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=2000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="net"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=2000.0),
        turn_count=6,
        asked_for_gross_amount=True,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is True
    assert plan.missing_fields == []


def test_net_takehome_above_threshold_skips_gross_followup() -> None:
    """Take-home already above gross limit → assess without asking for pre-tax."""
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=9000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="net"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=9000.0),
        turn_count=5,
        asked_for_gross_amount=False,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is True
    assert "approx_gross" not in plan.missing_fields


def test_individual_income_asks_for_household_total() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=3),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=1500.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="gross"),
        household_or_individual=CaseField(status=FieldStatus.KNOWN, value="individual"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=1500.0),
        turn_count=5,
        asked_for_household_total=False,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is False
    assert "approx_household_total" in plan.missing_fields


def test_individual_above_threshold_skips_household_followup() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=3),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=9000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="gross"),
        household_or_individual=CaseField(status=FieldStatus.KNOWN, value="individual"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=9000.0),
        turn_count=5,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is True
    assert "approx_household_total" not in plan.missing_fields


def test_net_then_individual_followup_order() -> None:
    """Net + individual under limit: ask pre-tax first, then household total."""
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=3),
        income_amount=CaseField(status=FieldStatus.KNOWN, value=1000.0),
        income_period=CaseField(status=FieldStatus.KNOWN, value="monthly"),
        gross_or_net=CaseField(status=FieldStatus.KNOWN, value="net"),
        household_or_individual=CaseField(status=FieldStatus.KNOWN, value="individual"),
        normalized_gross_monthly=CaseField(status=FieldStatus.UNCERTAIN, value=1000.0),
        turn_count=5,
        asked_for_gross_amount=False,
        asked_for_household_total=False,
    )
    plan = determine_missing_fields(case)
    assert plan.missing_fields[0] == "approx_gross"

    case.asked_for_gross_amount = True
    plan2 = determine_missing_fields(case)
    assert plan2.missing_fields[0] == "approx_household_total"


def test_uncertain_income_amount_clarifies() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.KNOWN, value=1),
        income_amount=CaseField(status=FieldStatus.UNCERTAIN, value=2500.0),
        turn_count=3,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is False
    assert "income_amount_clarify" in plan.missing_fields


def test_open_contradiction_blocks_assess() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.CONFLICTING, value=2),
        contradictions=[
            Contradiction(
                field="household_size",
                previous_value=2,
                proposed_value=4,
                turn=2,
                resolved=False,
            )
        ],
        turn_count=3,
    )
    plan = determine_missing_fields(case)
    assert plan.ready_to_assess is False
    assert plan.missing_fields[0].startswith("confirm_conflict")
    assert plan.stage == Stage.CLARIFYING
    assert "household_size" in plan.open_contradictions


def test_uncertain_field_sets_clarifying_stage() -> None:
    case = EligibilityCase(
        lives_in_nc=CaseField(status=FieldStatus.KNOWN, value=True),
        household_size=CaseField(status=FieldStatus.UNCERTAIN, value=2),
        turn_count=2,
    )
    plan = determine_missing_fields(case)
    assert plan.stage == Stage.CLARIFYING
    assert "household_size" in plan.missing_fields
