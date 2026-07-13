"""Agnostic eligibility helpers (income normalize) — no pack thresholds."""

from __future__ import annotations

import pytest
from src.eligibility.income import normalize_to_monthly


def test_normalize_income_all_periods() -> None:
    assert normalize_to_monthly(200, "daily") == round(200 * 365 / 12, 2)
    assert normalize_to_monthly(100, "weekly") == round(100 * 52 / 12, 2)
    assert normalize_to_monthly(1000, "biweekly") == round(1000 * 26 / 12, 2)
    assert normalize_to_monthly(1000, "semimonthly") == 2000.0  # * 24/12
    assert normalize_to_monthly(2500, "monthly") == 2500
    assert normalize_to_monthly(60000, "annual") == 5000


def test_normalize_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        normalize_to_monthly(-1, "monthly")
