"""Program pack and ruleset types (loaded from programs/{slug}/)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Ruleset:
    """
    Versioned screening rules for one program.

    effective_to is None when open-ended (no known end date).
    """

    id: str
    effective_from: str
    effective_to: str | None
    source_id: str
    description: str
    max_gross_monthly_by_size: Mapping[int, float]
    additional_member_increment: float
    program_slug: str = ""
    # Optional RAG source ids declared on the pack (not hardcoded NC FNS names)
    supporting_source_ids: tuple[str, ...] = ()

    def threshold_for_household(self, size: int) -> float:
        if size < 1:
            raise ValueError("household size must be >= 1")
        table = {int(k): float(v) for k, v in self.max_gross_monthly_by_size.items()}
        if size in table:
            return table[size]
        base = table[8]
        return base + (size - 8) * float(self.additional_member_increment)

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
    # Jurisdiction for residency gate (e.g. "North Carolina", "California")
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
