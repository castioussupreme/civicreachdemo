from __future__ import annotations

from typing import Literal

# Keep in sync with src.state.models.IncomePeriod and extraction coerce allow-list.
IncomePeriod = Literal[
    "daily",
    "weekly",
    "biweekly",
    "semimonthly",
    "monthly",
    "annual",
]

# Shared set for validation across extract/state layers
INCOME_PERIODS: frozenset[str] = frozenset(
    {"daily", "weekly", "biweekly", "semimonthly", "monthly", "annual"}
)


def normalize_to_monthly(amount: float, period: IncomePeriod) -> float:
    """
    Convert a recurring income amount to approximate monthly gross.

    - daily: amount * 365 / 12
    - weekly: amount * 52 / 12
    - biweekly (every two weeks): amount * 26 / 12
    - semimonthly (twice a month, e.g. 1st & 15th): amount * 24 / 12 = amount * 2
    - monthly / annual: as labeled
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if period == "daily":
        return round(amount * 365 / 12, 2)
    if period == "weekly":
        return round(amount * 52 / 12, 2)
    if period == "biweekly":
        return round(amount * 26 / 12, 2)
    if period == "semimonthly":
        return round(amount * 24 / 12, 2)
    if period == "monthly":
        return round(amount, 2)
    if period == "annual":
        return round(amount / 12, 2)
    raise ValueError(f"unknown period: {period}")
