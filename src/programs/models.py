"""Program pack and ruleset types (loaded from programs/{slug}/)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.eligibility.modules.base import RequirementSpec


@dataclass(frozen=True)
class Ruleset:
    """
    Versioned screening rules for one program.

    effective_to is None when open-ended (no known end date).
    Eligibility shape is entirely driven by ``requirements``.
    """

    id: str
    effective_from: str
    effective_to: str | None
    source_id: str
    description: str
    program_slug: str
    supporting_source_ids: tuple[str, ...]
    requirements: tuple[RequirementSpec, ...]

    def requirement_of_type(self, type_id: str) -> RequirementSpec | None:
        for req in self.requirements:
            if req.type == type_id:
                return req
        return None

    def gross_income_table(self) -> Mapping[int, float] | None:
        req = self.requirement_of_type("gross_income_limit")
        if req is None:
            return None
        table = req.params.get("max_gross_monthly_by_size")
        if not isinstance(table, dict):
            return None
        return {int(k): float(v) for k, v in table.items()}

    def gross_income_increment(self) -> float | None:
        req = self.requirement_of_type("gross_income_limit")
        if req is None:
            return None
        raw = req.params.get("additional_member_increment")
        if raw is None:
            return 0.0
        return float(str(raw))

    def threshold_for_household(self, size: int) -> float:
        """Convenience when a gross_income_limit module is declared; else raises."""
        # Local import avoids programs ↔ eligibility package cycle at import time.
        from src.eligibility.thresholds import (  # noqa: PLC0415
            threshold_for_household as thr_fn,
        )

        table = self.gross_income_table()
        increment = self.gross_income_increment()
        if table is None or increment is None:
            raise ValueError(f"ruleset {self.id} has no gross_income_limit requirement")
        return thr_fn(table, increment, size)

    def effective_from_date(self) -> date:
        return date.fromisoformat(self.effective_from)

    def effective_to_date(self) -> date | None:
        if self.effective_to is None or self.effective_to == "":
            return None
        return date.fromisoformat(self.effective_to)

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from_date():
            return False
        end = self.effective_to_date()
        return not (end is not None and as_of > end)

    def days_until_end(self, as_of: date) -> int | None:
        end = self.effective_to_date()
        if end is None:
            return None
        return (end - as_of).days


@dataclass(frozen=True)
class ProgramMeta:
    slug: str
    display_name: str
    search_aliases: tuple[str, ...]
    program_effective_from: str | None
    program_effective_to: str | None
    opening_message: str
    root: Path
    service_area_name: str = ""
    service_area_short: str = ""

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def rules_dir(self) -> Path:
        return self.root / "rules"

    @property
    def smoke_dir(self) -> Path:
        return self.root / "smoke"

    def matches_query(self, q: str) -> bool:
        if not q:
            return True
        needle = q.strip().lower()
        hay = " ".join(
            [
                self.slug,
                self.display_name,
                *self.search_aliases,
            ]
        ).lower()
        return needle in hay

    def program_active(self, as_of: date) -> bool:
        if self.program_effective_from and as_of < date.fromisoformat(self.program_effective_from):
            return False
        return not (
            self.program_effective_to and as_of > date.fromisoformat(self.program_effective_to)
        )


@dataclass(frozen=True)
class CatalogEntry:
    slug: str
    display_name: str
    ruleset_id: str
    effective_from: str
    effective_to: str | None
    search_aliases: tuple[str, ...]
