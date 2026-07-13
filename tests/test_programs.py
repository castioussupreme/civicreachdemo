"""Program registry, catalog search, ruleset resolution."""

from __future__ import annotations

from datetime import date

import pytest
from src.programs.registry import (
    ProgramNotAvailableError,
    catalog_programs,
    default_program_slug,
    get_program,
    list_enabled_slugs,
    resolve_ruleset,
)


def test_default_program_is_nc_fns() -> None:
    assert default_program_slug() == "nc-fns"
    assert "nc-fns" in list_enabled_slugs()


def test_get_program_metadata() -> None:
    p = get_program("nc-fns")
    assert "Food" in p.display_name or "FNS" in p.display_name or "SNAP" in p.display_name
    assert p.knowledge_dir.is_dir()
    assert p.rules_dir.is_dir()
    assert p.matches_query("snap")
    assert p.matches_query("food")


def test_resolve_ruleset_current_fy() -> None:
    rs = resolve_ruleset("nc-fns", date(2026, 3, 1))
    assert rs.id == "nc-fns-screening-2025-10"
    assert rs.threshold_for_household(2) == 3526.0
    assert rs.covers(date(2026, 3, 1))
    assert not rs.covers(date(2024, 1, 1))


def test_resolve_ruleset_outside_window() -> None:
    with pytest.raises(ProgramNotAvailableError):
        resolve_ruleset("nc-fns", date(2024, 1, 1))


def test_catalog_search() -> None:
    all_p = catalog_programs(q="", as_of=date(2026, 1, 15), limit=10)
    assert any(e.slug == "nc-fns" for e in all_p)
    filtered = catalog_programs(q="SNAP", as_of=date(2026, 1, 15), limit=10)
    assert len(filtered) >= 1
    assert filtered[0].slug == "nc-fns"
    none = catalog_programs(q="zzzz-not-a-program", as_of=date(2026, 1, 15), limit=10)
    assert none == []
