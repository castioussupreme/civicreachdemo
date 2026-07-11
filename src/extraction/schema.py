"""Structured extraction types (no typing.Any)."""

from __future__ import annotations

from typing import Literal, TypedDict, cast

from src.state.models import GrossOrNet, HouseholdOrIndividual, IncomePeriod

UserIntent = Literal[
    "eligibility_screening",
    "policy_question",
    "greeting",
    "other",
]

ConfirmableValue = bool | int | float | str


class ExtractionFacts(TypedDict, total=False):
    lives_in_nc: bool | None
    lives_in_nc_raw: str
    household_size: int | None
    household_size_raw: str
    income_amount: float | None
    income_amount_raw: str
    income_period: IncomePeriod | None
    gross_or_net: GrossOrNet | None
    household_or_individual: HouseholdOrIndividual | None
    is_student: bool | None
    elderly_or_disabled_member: bool | None
    confirm_field: str | None
    confirm_value: ConfirmableValue | None
    confidence: dict[str, float]


class ExtractionResult(TypedDict, total=False):
    facts: ExtractionFacts
    user_intents: list[str]
    policy_question: str | None
    notes: str | None


def empty_facts() -> ExtractionFacts:
    return {"confidence": {}}


def coerce_extraction(data: object) -> ExtractionResult:
    """Best-effort normalize LLM JSON into ExtractionResult."""
    if not isinstance(data, dict):
        return {"facts": empty_facts(), "user_intents": ["eligibility_screening"]}

    raw_facts = data.get("facts")
    if isinstance(raw_facts, dict):
        return {
            "facts": _coerce_facts(raw_facts),
            "user_intents": _str_list(data.get("user_intents")),
            "policy_question": _opt_str(data.get("policy_question")),
            "notes": _opt_str(data.get("notes")),
        }

    # Model returned flat facts object
    return {
        "facts": _coerce_facts(data),
        "user_intents": ["eligibility_screening"],
    }


def _coerce_facts(raw: object) -> ExtractionFacts:
    if not isinstance(raw, dict):
        return empty_facts()

    facts = empty_facts()
    confidence: dict[str, float] = {}
    conf_raw = raw.get("confidence")
    if isinstance(conf_raw, dict):
        for key, val in conf_raw.items():
            if isinstance(key, str):
                parsed = _as_float(val)
                if parsed is not None:
                    confidence[key] = parsed
    facts["confidence"] = confidence

    if raw.get("lives_in_nc") is not None:
        facts["lives_in_nc"] = bool(raw["lives_in_nc"])

    size = _as_int(raw.get("household_size"))
    if size is not None:
        facts["household_size"] = size

    amount = _as_float(raw.get("income_amount"))
    if amount is not None:
        facts["income_amount"] = amount

    period = raw.get("income_period")
    if isinstance(period, str) and period in {"weekly", "biweekly", "monthly", "annual"}:
        facts["income_period"] = cast(IncomePeriod, period)

    gon = raw.get("gross_or_net")
    if isinstance(gon, str) and gon in {"gross", "net"}:
        facts["gross_or_net"] = cast(GrossOrNet, gon)

    hoi = raw.get("household_or_individual")
    if isinstance(hoi, str) and hoi in {"household", "individual"}:
        facts["household_or_individual"] = cast(HouseholdOrIndividual, hoi)

    if raw.get("is_student") is not None:
        facts["is_student"] = bool(raw["is_student"])
    if raw.get("elderly_or_disabled_member") is not None:
        facts["elderly_or_disabled_member"] = bool(raw["elderly_or_disabled_member"])

    confirm_field = raw.get("confirm_field")
    if isinstance(confirm_field, str):
        facts["confirm_field"] = confirm_field
    confirm_value = raw.get("confirm_value")
    if isinstance(confirm_value, bool | int | float | str):
        facts["confirm_value"] = confirm_value

    lives_raw = raw.get("lives_in_nc_raw")
    if isinstance(lives_raw, str):
        facts["lives_in_nc_raw"] = lives_raw
    hh_raw = raw.get("household_size_raw")
    if isinstance(hh_raw, str):
        facts["household_size_raw"] = hh_raw
    inc_raw = raw.get("income_amount_raw")
    if isinstance(inc_raw, str):
        facts["income_amount_raw"] = inc_raw

    return facts


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return ["eligibility_screening"]
    return [str(item) for item in value]


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
