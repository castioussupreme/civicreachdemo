"""
Versioned NC FNS screening rules (code path — authoritative for eligibility math).

DUAL COPY — keep in sync with the RAG/display table:
  knowledge/nc-fns-income-limits.md
  knowledge/manifest.json  (source id nc-fns-income-limits)
See AGENTS.md ("Dual copy of income thresholds").

Public provenance (both copies):
  More In My Basket - Am I Eligible?
  https://morefood.org/using-snap/am-i-eligible/
  Table: Maximum Gross Monthly Income (200%), effective 2025-10-01 - 2026-09-30
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Ruleset:
    """
    Versioned NC FNS screening rules loaded in process memory.

    Thresholds mirror knowledge/nc-fns-income-limits.md (same public table).
    Some households face a 130% test determined by DSS — this POC does not
    independently decide which percentage applies.
    """

    id: str
    effective_from: str
    effective_to: str
    source_id: str
    description: str
    max_gross_monthly_by_size: Mapping[int, float]
    additional_member_increment: float

    def threshold_for_household(self, size: int) -> float:
        if size < 1:
            raise ValueError("household size must be >= 1")
        if size in self.max_gross_monthly_by_size:
            return float(self.max_gross_monthly_by_size[size])
        # Extrapolate from size 8
        base = float(self.max_gross_monthly_by_size[8])
        return base + (size - 8) * self.additional_member_increment


# Must match knowledge/nc-fns-income-limits.md gross monthly table (+$918 per extra member).
RULESET = Ruleset(
    id="nc-fns-screening-2025-10",
    effective_from="2025-10-01",
    effective_to="2026-09-30",
    source_id="nc-fns-income-limits",
    description=(
        "Simplified NC FNS gross monthly income screen using the public 200% table. "
        "Not an official determination; DSS may apply a 130% test or other rules."
    ),
    max_gross_monthly_by_size={
        1: 2610.0,
        2: 3526.0,
        3: 4442.0,
        4: 5360.0,
        5: 6276.0,
        6: 7194.0,
        7: 8112.0,
        8: 9030.0,
    },
    additional_member_increment=918.0,
)
