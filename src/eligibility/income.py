from __future__ import annotations

from typing import Literal

# Keep in sync with src.state.models.IncomePeriod and extraction coerce allow-list.
IncomePeriod = Literal["daily", "weekly", "biweekly", "monthly", "annual"]

# Shared set for validation across extract/state layers
INCOME_PERIODS: frozenset[str] = frozenset({"daily", "weekly", "biweekly", "monthly", "annual"})


def normalize_to_monthly(amount: float, period: IncomePeriod) -> float:
    """
    Convert a recurring income amount to approximate monthly gross.

    Daily uses a 365-day year (amount * 365 / 12), consistent with weekly (52/12)
    and biweekly (26/12) year-based scaling.
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if period == "daily":
        return round(amount * 365 / 12, 2)
    if period == "weekly":
        return round(amount * 52 / 12, 2)
    if period == "biweekly":
        return round(amount * 26 / 12, 2)
    if period == "monthly":
        return round(amount, 2)
    if period == "annual":
        return round(amount / 12, 2)
    raise ValueError(f"unknown period: {period}")
