from __future__ import annotations

from typing import TypeVar

from src.eligibility.income import normalize_to_monthly
from src.extraction.schema import ExtractionFacts, ExtractionResult, as_bool, as_float, as_int
from src.state.models import (
    CaseField,
    Contradiction,
    EligibilityCase,
    FieldStatus,
    GrossOrNet,
    HouseholdOrIndividual,
    IncomePeriod,
    ScalarValue,
)

T = TypeVar("T")

_BOOL_FIELDS = frozenset(
    {
        "lives_in_service_area",
        "is_student",
        "elderly_or_disabled_member",
    }
)
_INT_FIELDS = frozenset({"household_size"})
_FLOAT_FIELDS = frozenset({"income_amount", "normalized_gross_monthly"})
_PERIOD_FIELDS = frozenset({"income_period"})
_GROSS_NET_FIELDS = frozenset({"gross_or_net"})
_HOI_FIELDS = frozenset({"household_or_individual"})


def _set_field(
    field: CaseField[T],
    value: T,
    *,
    raw: str | None,
    confidence: float | None,
    turn: int,
    path: str,
    case: EligibilityCase,
) -> None:
    # Uncertain extraction: record without overwriting a solid known value
    if confidence is not None and confidence < 0.55:
        if field.status == FieldStatus.UNKNOWN:
            field.status = FieldStatus.UNCERTAIN
            field.value = value
            field.raw_value = raw
            field.confidence = confidence
            field.source_turn = turn
        return

    if field.status == FieldStatus.KNOWN and field.value is not None and field.value != value:
        case.contradictions.append(
            Contradiction(
                field=path,
                previous_value=_as_scalar(field.value),
                proposed_value=_as_scalar(value),
                turn=turn,
                resolved=False,
                note=f"User may have changed {path}",
            )
        )
        field.status = FieldStatus.CONFLICTING
        field.raw_value = raw
        field.confidence = confidence
        field.source_turn = turn
        # Keep previous value until user confirms; still store proposed in notes
        case.notes.append(
            f"Turn {turn}: conflict on {path}: previous={field.value!r}, proposed={value!r}"
        )
        return

    field.status = FieldStatus.KNOWN
    field.value = value
    field.raw_value = raw
    field.confidence = confidence
    field.source_turn = turn


def _as_scalar(value: object) -> ScalarValue | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | str):
        return value
    return str(value)


def apply_validated_updates(
    case: EligibilityCase,
    extraction: ExtractionResult,
    *,
    turn: int,
) -> EligibilityCase:
    """
    Apply structured extraction to case state.
    Code-owned: contradiction detection, type coercion, income normalization.
    """
    facts: ExtractionFacts = extraction.get("facts") or {}

    lives_in_service_area = facts.get("lives_in_service_area")
    if lives_in_service_area is not None:
        # Already strict-bool from coerce; re-check before write
        lives = as_bool(lives_in_service_area)
        if lives is not None:
            _set_field(
                case.lives_in_service_area,
                lives,
                raw=str(facts.get("lives_in_service_area_raw") or lives),
                confidence=_conf(facts, "lives_in_service_area"),
                turn=turn,
                path="lives_in_service_area",
                case=case,
            )

    household_size = facts.get("household_size")
    if household_size is not None:
        size = int(household_size)
        if size < 1 or size > 30:
            case.notes.append(f"Turn {turn}: ignored implausible household_size={size}")
        else:
            _set_field(
                case.household_size,
                size,
                raw=str(facts.get("household_size_raw") or size),
                confidence=_conf(facts, "household_size"),
                turn=turn,
                path="household_size",
                case=case,
            )

    income_amount = facts.get("income_amount")
    if income_amount is not None:
        amount = float(income_amount)
        if amount < 0 or amount > 1_000_000:
            case.notes.append(f"Turn {turn}: ignored implausible income_amount={amount}")
        else:
            _set_field(
                case.income_amount,
                amount,
                raw=str(facts.get("income_amount_raw") or amount),
                confidence=_conf(facts, "income_amount"),
                turn=turn,
                path="income_amount",
                case=case,
            )

    period = facts.get("income_period")
    if period is not None and period in {
        "daily",
        "weekly",
        "biweekly",
        "semimonthly",
        "monthly",
        "annual",
    }:
        typed_period: IncomePeriod = period
        _set_field(
            case.income_period,
            typed_period,
            raw=typed_period,
            confidence=_conf(facts, "income_period"),
            turn=turn,
            path="income_period",
            case=case,
        )

    gon = facts.get("gross_or_net")
    if gon is not None and gon in {"gross", "net"}:
        typed_gon: GrossOrNet = gon
        _set_field(
            case.gross_or_net,
            typed_gon,
            raw=typed_gon,
            confidence=_conf(facts, "gross_or_net"),
            turn=turn,
            path="gross_or_net",
            case=case,
        )

    hoi = facts.get("household_or_individual")
    if hoi is not None and hoi in {"household", "individual"}:
        typed_hoi: HouseholdOrIndividual = hoi
        _set_field(
            case.household_or_individual,
            typed_hoi,
            raw=typed_hoi,
            confidence=_conf(facts, "household_or_individual"),
            turn=turn,
            path="household_or_individual",
            case=case,
        )

    is_student = facts.get("is_student")
    if is_student is not None:
        student = as_bool(is_student)
        if student is not None:
            _set_field(
                case.is_student,
                student,
                raw=str(student),
                confidence=_conf(facts, "is_student"),
                turn=turn,
                path="is_student",
                case=case,
            )

    elderly = facts.get("elderly_or_disabled_member")
    if elderly is not None:
        flag = as_bool(elderly)
        if flag is not None:
            _set_field(
                case.elderly_or_disabled_member,
                flag,
                raw=str(flag),
                confidence=_conf(facts, "elderly_or_disabled_member"),
                turn=turn,
                path="elderly_or_disabled_member",
                case=case,
            )

    # Confirmation of a conflicting field (typed — never raw LLM strings on bool slots)
    confirm_field = facts.get("confirm_field")
    confirm_value = facts.get("confirm_value")
    if confirm_field and confirm_value is not None:
        _resolve_conflict(case, str(confirm_field), confirm_value, turn)

    _recompute_normalized_income(case, turn)
    return case


def _conf(facts: ExtractionFacts, key: str) -> float | None:
    conf_map = facts.get("confidence") or {}
    if key in conf_map:
        try:
            return float(conf_map[key])
        except (TypeError, ValueError):
            return None
    return 0.8


def _coerce_confirm_value(path: str, value: ScalarValue) -> ScalarValue | None:
    """Map confirm_value onto the field's real type; None = drop (do not write)."""
    if path in _BOOL_FIELDS:
        return as_bool(value)
    if path in _INT_FIELDS:
        return as_int(value)
    if path in _FLOAT_FIELDS:
        return as_float(value)
    if path in _PERIOD_FIELDS:
        if isinstance(value, str) and value in {
            "daily",
            "weekly",
            "biweekly",
            "semimonthly",
            "monthly",
            "annual",
        }:
            return value
        return None
    if path in _GROSS_NET_FIELDS:
        if isinstance(value, str) and value in {"gross", "net"}:
            return value
        return None
    if path in _HOI_FIELDS:
        if isinstance(value, str) and value in {"household", "individual"}:
            return value
        return None
    # Unknown path — only pass through already-scalar typed values
    if isinstance(value, bool | int | float | str):
        return value
    return None


def _resolve_conflict(
    case: EligibilityCase,
    path: str,
    value: ScalarValue,
    turn: int,
) -> None:
    field = getattr(case, path, None)
    if not isinstance(field, CaseField):
        return
    coerced = _coerce_confirm_value(path, value)
    if coerced is None:
        case.notes.append(f"Turn {turn}: ignored untyped confirm for {path}: {value!r}")
        return
    # Path-specific coerce already typed the value for this field
    field.status = FieldStatus.KNOWN
    field.value = coerced
    field.source_turn = turn
    for c in case.contradictions:
        if c.field == path and not c.resolved:
            c.resolved = True


def _recompute_normalized_income(case: EligibilityCase, turn: int) -> None:
    """Normalize only when amount + period are known and not net-only uncertainty."""
    if not case.income_amount.is_usable() or not case.income_period.is_usable():
        return

    amount_val = case.income_amount.value
    period_val = case.income_period.value
    if amount_val is None or period_val is None:
        return

    amount = float(amount_val)
    period: IncomePeriod = period_val
    monthly = normalize_to_monthly(amount, period)

    # If user said net, we still store a provisional figure but mark uncertain
    if case.gross_or_net.is_usable() and case.gross_or_net.value == "net":
        case.normalized_gross_monthly.status = FieldStatus.UNCERTAIN
        case.normalized_gross_monthly.value = monthly
        case.normalized_gross_monthly.raw_value = f"net {amount} {period} -> monthly {monthly}"
        case.normalized_gross_monthly.source_turn = turn
        return

    # Individual income with household size > 1 → uncertain unless marked household
    hh = case.household_size.value
    if (
        case.household_or_individual.is_usable()
        and case.household_or_individual.value == "individual"
        and case.household_size.is_usable()
        and hh is not None
        and int(hh) > 1
    ):
        case.normalized_gross_monthly.status = FieldStatus.UNCERTAIN
        case.normalized_gross_monthly.value = monthly
        case.normalized_gross_monthly.raw_value = (
            f"individual {amount} {period} -> monthly {monthly} (may not be full household)"
        )
        case.normalized_gross_monthly.source_turn = turn
        return

    case.normalized_gross_monthly.status = FieldStatus.KNOWN
    case.normalized_gross_monthly.value = monthly
    case.normalized_gross_monthly.raw_value = f"{amount} {period} -> {monthly}"
    case.normalized_gross_monthly.source_turn = turn
