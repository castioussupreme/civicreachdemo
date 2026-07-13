"""Gross monthly income limit screen (table-driven)."""

from __future__ import annotations

from collections.abc import Mapping

from src.eligibility.income import normalize_to_monthly
from src.eligibility.modules.base import (
    MissingItem,
    ModuleOutcome,
    ModuleResult,
    RequirementSpec,
    _as_bool,
    _as_float,
    _as_str,
    reject_unknown_keys,
)
from src.eligibility.thresholds import parse_income_table, threshold_for_household
from src.programs.models import ProgramMeta
from src.state.models import EligibilityCase, FieldStatus

_ALLOWED = frozenset(
    {
        "max_gross_monthly_by_size",
        "additional_member_increment",
        "ask_gross_vs_net",
        "ask_household_vs_individual",
        "stricter_test_source_id",
    }
)


def _stated_monthly(case: EligibilityCase) -> float | None:
    if not case.income_amount.is_usable() or not case.income_period.is_usable():
        return None
    amount = case.income_amount.value
    period = case.income_period.value
    if amount is None or period is None:
        return None
    return normalize_to_monthly(float(amount), period)


class GrossIncomeLimitModule:
    type_id = "gross_income_limit"

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        reject_unknown_keys(params, _ALLOWED, self.type_id)
        try:
            table = parse_income_table(params.get("max_gross_monthly_by_size"))
        except ValueError as exc:
            raise ValueError(f"gross_income_limit: {exc}") from exc
        increment = _as_float(params.get("additional_member_increment"), 0.0)
        ask_gross = _as_bool(params.get("ask_gross_vs_net"), True)
        ask_hh = _as_bool(params.get("ask_household_vs_individual"), True)
        stricter = _as_str(params.get("stricter_test_source_id"), "") or None
        return {
            "max_gross_monthly_by_size": table,
            "additional_member_increment": increment,
            "ask_gross_vs_net": ask_gross,
            "ask_household_vs_individual": ask_hh,
            "stricter_test_source_id": stricter,
        }

    def missing(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
    ) -> list[MissingItem]:
        _ = program
        ask_gross = bool(spec.params.get("ask_gross_vs_net", True))
        ask_hh = bool(spec.params.get("ask_household_vs_individual", True))
        table_raw = spec.params["max_gross_monthly_by_size"]
        assert isinstance(table_raw, dict)
        table: dict[int, float] = {int(k): float(v) for k, v in table_raw.items()}
        increment = _as_float(spec.params.get("additional_member_increment"), 0.0)

        missing: list[MissingItem] = []

        if case.income_amount.status == FieldStatus.UNKNOWN:
            missing.append(
                MissingItem(
                    field_key="income_amount",
                    question_hint=(
                        "About how much income does your household get before taxes? "
                        "A round number is fine — per day, weekly, every two weeks, twice a month, "
                        "monthly, or yearly."
                    ),
                )
            )
        elif case.income_amount.status == FieldStatus.UNCERTAIN:
            missing.append(
                MissingItem(
                    field_key="income_amount_clarify",
                    question_hint=(
                        "I want to make sure I have the right income figure. "
                        "About how much is it, and is that per day, weekly, every two weeks, "
                        "twice a month, monthly, or yearly?"
                    ),
                )
            )

        if case.income_amount.is_usable() and case.income_period.status in (
            FieldStatus.UNKNOWN,
            FieldStatus.UNCERTAIN,
        ):
            missing.append(
                MissingItem(
                    field_key="income_period",
                    question_hint=(
                        "Is that amount per day, weekly, every two weeks, twice a month "
                        "(like the 1st and 15th), monthly, or yearly?"
                    ),
                )
            )

        if (
            ask_gross
            and case.income_amount.is_usable()
            and case.gross_or_net.status == FieldStatus.UNKNOWN
        ):
            missing.append(
                MissingItem(
                    field_key="gross_or_net",
                    question_hint="Is that roughly before taxes, or take-home pay after taxes?",
                )
            )

        if (
            ask_hh
            and case.household_size.is_usable()
            and case.household_size.value is not None
            and int(case.household_size.value) > 1
            and case.income_amount.is_usable()
            and case.household_or_individual.status == FieldStatus.UNKNOWN
        ):
            missing.append(
                MissingItem(
                    field_key="household_or_individual",
                    question_hint=(
                        "Is that the total for everyone in the household, or just your income?"
                    ),
                )
            )

        # One-shot follow-ups when income incomplete (no invented math)
        if not missing and case.normalized_gross_monthly.status == FieldStatus.UNCERTAIN:
            exceeds = False
            monthly = _stated_monthly(case)
            if (
                monthly is not None
                and case.household_size.is_usable()
                and case.household_size.value is not None
            ):
                thr = threshold_for_household(table, increment, int(case.household_size.value))
                exceeds = monthly > thr

            if not exceeds:
                is_net = case.gross_or_net.is_usable() and case.gross_or_net.value == "net"
                is_individual = (
                    case.household_or_individual.is_usable()
                    and case.household_or_individual.value == "individual"
                    and case.household_size.is_usable()
                    and case.household_size.value is not None
                    and int(case.household_size.value) > 1
                )
                if is_net and not case.asked_for_gross_amount:
                    missing.append(
                        MissingItem(
                            field_key="approx_gross",
                            question_hint=(
                                "This screen uses income before taxes (gross), not take-home pay. "
                                "About how much is that amount before taxes, if you know? "
                                "A rough number is fine — or say if you only know take-home."
                            ),
                        )
                    )
                elif is_individual and not case.asked_for_household_total:
                    missing.append(
                        MissingItem(
                            field_key="approx_household_total",
                            question_hint=(
                                "This screen needs total household income for everyone who buys "
                                "and prepares food together — not just one person's pay. "
                                "About how much is the household total before taxes, if you know? "
                                "A rough number is fine — or say if you only know your own."
                            ),
                        )
                    )

        return missing

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
        _ = program, ruleset
        table_raw = spec.params["max_gross_monthly_by_size"]
        assert isinstance(table_raw, dict)
        table: dict[int, float] = {int(k): float(v) for k, v in table_raw.items()}
        increment = _as_float(spec.params.get("additional_member_increment"), 0.0)
        stricter = _as_str(spec.params.get("stricter_test_source_id"), "") or None

        source_ids = [s for s in (ruleset_source_id, *supporting_source_ids) if s]
        caveats: list[str] = []
        if stricter and stricter in supporting_source_ids:
            caveats.append(
                "Some households may face a stricter (~130%) gross income test; only the agency "
                "decides which test applies (this screen uses the public 200% table only)."
            )

        if not case.household_size.is_usable() or case.household_size.value is None:
            return ModuleResult(
                outcome=ModuleOutcome.NEED_MORE,
                reasons=["Household size is missing or not confirmed."],
                source_ids=source_ids,
                caveats=caveats,
            )

        income_status = case.normalized_gross_monthly.status
        if income_status == FieldStatus.UNKNOWN or case.normalized_gross_monthly.value is None:
            cite = list(dict.fromkeys([*source_ids, ruleset_source_id]))
            if case.income_amount.status == FieldStatus.UNCERTAIN:
                return ModuleResult(
                    outcome=ModuleOutcome.NEED_MORE,
                    reasons=[
                        "Income was stated approximately; need a clearer amount "
                        "and whether it is daily/weekly/monthly and gross household income."
                    ],
                    source_ids=cite,
                    caveats=caveats,
                )
            return ModuleResult(
                outcome=ModuleOutcome.NEED_MORE,
                reasons=["Gross household monthly income is not yet established."],
                source_ids=cite,
                caveats=caveats,
            )

        size = int(case.household_size.value)
        monthly = float(case.normalized_gross_monthly.value)
        threshold = threshold_for_household(table, increment, size)
        cite = list(dict.fromkeys([*source_ids, ruleset_source_id]))

        if income_status == FieldStatus.UNCERTAIN:
            return _assess_uncertain(
                case=case,
                monthly=monthly,
                size=size,
                threshold=threshold,
                source_ids=cite,
                caveats=caveats,
                ruleset_source_id=ruleset_source_id,
            )

        under = monthly <= threshold
        if under:
            return ModuleResult(
                outcome=ModuleOutcome.PASS,
                reasons=[
                    f"Normalized gross monthly income ${monthly:,.2f} is at or below "
                    f"the public screening threshold ${threshold:,.2f} for a household of {size}."
                ],
                source_ids=cite,
                caveats=caveats,
                threshold_used=threshold,
                normalized_gross_monthly=monthly,
                household_size=size,
            )
        return ModuleResult(
            outcome=ModuleOutcome.FAIL,
            reasons=[
                f"Normalized gross monthly income ${monthly:,.2f} is above "
                f"the public screening threshold ${threshold:,.2f} for a household of {size}."
            ],
            source_ids=cite,
            caveats=caveats,
            threshold_used=threshold,
            normalized_gross_monthly=monthly,
            household_size=size,
        )


def _assess_uncertain(
    *,
    case: EligibilityCase,
    monthly: float,
    size: int,
    threshold: float,
    source_ids: list[str],
    caveats: list[str],
    ruleset_source_id: str,
) -> ModuleResult:
    is_net = case.gross_or_net.is_usable() and case.gross_or_net.value == "net"
    is_individual = (
        case.household_or_individual.is_usable()
        and case.household_or_individual.value == "individual"
        and size > 1
    )
    cite = list(dict.fromkeys([*source_ids, ruleset_source_id]))

    if monthly > threshold and (is_net or is_individual):
        if is_net and is_individual:
            bound_why = (
                f"You shared take-home income for one person of about ${monthly:,.2f}/month. "
                f"Full household before-tax income is at least that high."
            )
        elif is_net:
            bound_why = (
                f"You shared take-home (after-tax) income of about ${monthly:,.2f}/month. "
                f"Before-tax income is at least that high."
            )
        else:
            bound_why = (
                f"You shared one person's income of about ${monthly:,.2f}/month. "
                f"Total household income is at least that high."
            )
        return ModuleResult(
            outcome=ModuleOutcome.FAIL,
            reasons=[
                f"{bound_why} The public gross limit for a household of {size} is "
                f"${threshold:,.2f} — so this simple screen points to likely not eligible."
            ],
            source_ids=cite,
            threshold_used=threshold,
            normalized_gross_monthly=monthly,
            household_size=size,
            caveats=[
                *caveats,
                "Bound uses a lower bound on income (take-home and/or one person only); "
                "no tax reverse-calculation or invented household totals.",
            ],
        )

    extra: list[str] = []
    if is_net:
        extra.append(
            "Income was given as take-home (after taxes). This screen compares "
            "before-tax (gross) income to the public table. We do not reverse-calculate "
            "gross from tax brackets — that would be guesswork."
        )
    if is_individual:
        extra.append(
            "Income may be for one person only; screening needs total household income "
            "for everyone who buys and prepares food together. We do not invent "
            "other members' earnings."
        )

    parts: list[str] = []
    if is_net:
        parts.append("take-home")
    if is_individual:
        parts.append("one-person")
    label = " / ".join(parts) if parts else "provisional"

    return ModuleResult(
        outcome=ModuleOutcome.UNABLE,
        reasons=extra or ["Income details are too uncertain to complete a reliable gross screen."],
        source_ids=cite,
        threshold_used=threshold,
        normalized_gross_monthly=monthly,
        household_size=size,
        caveats=[
            *caveats,
            f"Your {label} amount normalized to about ${monthly:,.2f}/month "
            f"(not confirmed full gross household income). Public gross threshold for "
            f"household of {size}: ${threshold:,.2f}. "
            f"If you know approximate before-tax total household income, we can re-run "
            f"this simple screen; otherwise the agency can review a full application.",
        ],
    )
