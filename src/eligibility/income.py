from __future__ import annotations

from typing import Literal

IncomePeriod = Literal["weekly", "biweekly", "monthly", "annual"]


def normalize_to_monthly(amount: float, period: IncomePeriod) -> float:
    """Convert a recurring income amount to approximate monthly gross."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if period == "weekly":
        return round(amount * 52 / 12, 2)
    if period == "biweekly":
        return round(amount * 26 / 12, 2)
    if period == "monthly":
        return round(amount, 2)
    if period == "annual":
        return round(amount / 12, 2)
    raise ValueError(f"unknown period: {period}")
