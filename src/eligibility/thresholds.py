"""Pure household-size income threshold math (no pack imports)."""

from __future__ import annotations

from collections.abc import Mapping


def threshold_for_household(
    table: Mapping[int, float],
    increment: float,
    size: int,
) -> float:
    if size < 1:
        raise ValueError("household size must be >= 1")
    t = {int(k): float(v) for k, v in table.items()}
    if size in t:
        return t[size]
    if 8 not in t:
        raise ValueError("income table must include size 8 (extrapolation base)")
    return t[8] + (size - 8) * float(increment)


def parse_income_table(raw: object) -> dict[int, float]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("max_gross_monthly_by_size must be a non-empty map")
    table: dict[int, float] = {}
    for k, v in raw.items():
        table[int(str(k))] = float(str(v))
    if 8 not in table:
        raise ValueError("table must include size 8 (extrapolation base)")
    return table
