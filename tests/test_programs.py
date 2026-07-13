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


def test_resolve_ruleset_prior_fy() -> None:
    """Prior FFY (2024-10) table for as_of before Oct 2025."""
    rs = resolve_ruleset("nc-fns", date(2025, 3, 1))
    assert rs.id == "nc-fns-screening-2024-10"
    assert rs.threshold_for_household(2) == 3408.0
    assert rs.covers(date(2025, 9, 30))
    assert not rs.covers(date(2025, 10, 1))


def test_resolve_ruleset_last_day_of_prior_fy() -> None:
    rs = resolve_ruleset("nc-fns", date(2025, 9, 30))
    assert rs.id == "nc-fns-screening-2024-10"
    assert rs.threshold_for_household(2) == 3408.0


def test_resolve_ruleset_outside_window() -> None:
    with pytest.raises(ProgramNotAvailableError):
        resolve_ruleset("nc-fns", date(2023, 1, 1))


def test_catalog_lists_active_ruleset_for_as_of() -> None:
    prior = catalog_programs(q="nc-fns", as_of=date(2025, 3, 1), limit=10)
    assert prior and prior[0].ruleset_id == "nc-fns-screening-2024-10"
    current = catalog_programs(q="nc-fns", as_of=date(2026, 1, 15), limit=10)
    assert current and current[0].ruleset_id == "nc-fns-screening-2025-10"


def test_catalog_search() -> None:
    all_p = catalog_programs(q="", as_of=date(2026, 1, 15), limit=10)
    assert {e.slug for e in all_p} >= {"nc-fns", "ca-calfresh"}
    # SNAP is an alias for both programs; both may match
    filtered = catalog_programs(q="SNAP", as_of=date(2026, 1, 15), limit=10)
    assert {e.slug for e in filtered} >= {"nc-fns", "ca-calfresh"}
    none = catalog_programs(q="zzzz-not-a-program", as_of=date(2026, 1, 15), limit=10)
    assert none == []
