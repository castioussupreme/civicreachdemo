"""Agnostic program registry / catalog (multi-pack infrastructure)."""

from __future__ import annotations

from datetime import date

from src.programs.models import program_text_matches
from src.programs.registry import catalog_programs, get_program, list_enabled_slugs


def test_registry_lists_enabled_packs() -> None:
    slugs = list_enabled_slugs()
    assert "nc-fns" in slugs
    assert "ca-calfresh" in slugs


def test_catalog_search_across_packs() -> None:
    all_p = catalog_programs(q="", as_of=date(2026, 1, 15), limit=10)
    assert {e.slug for e in all_p} >= {"nc-fns", "ca-calfresh"}
    # SNAP is an alias for both programs; both may match
    filtered = catalog_programs(q="SNAP", as_of=date(2026, 1, 15), limit=10)
    assert {e.slug for e in filtered} >= {"nc-fns", "ca-calfresh"}
    none = catalog_programs(q="zzzz-not-a-program", as_of=date(2026, 1, 15), limit=10)
    assert none == []


def test_program_text_matches_short_token_prefix_not_midword() -> None:
    """'nc' must not match 'assistance' (old substring bug)."""
    assert program_text_matches("nc", "nc-fns", "NC Food", "assistance program")
    assert not program_text_matches("nc", "ca-calfresh", "California CalFresh", "food assistance")
    assert program_text_matches("cal", "ca-calfresh", "California CalFresh", "CalFresh")
    assert program_text_matches("nutrition", "nc-fns", "NC Food & Nutrition Services")


def test_catalog_nc_filter_excludes_calfresh() -> None:
    hits = catalog_programs(q="nc", as_of=date(2026, 1, 15), limit=10)
    slugs = {e.slug for e in hits}
    assert "nc-fns" in slugs
    assert "ca-calfresh" not in slugs


def test_catalog_cal_filter_excludes_nc_fns() -> None:
    hits = catalog_programs(q="calfresh", as_of=date(2026, 1, 15), limit=10)
    slugs = {e.slug for e in hits}
    assert "ca-calfresh" in slugs
    assert "nc-fns" not in slugs


def test_get_program_matches_query_uses_same_rules() -> None:
    nc = get_program("nc-fns")
    cal = get_program("ca-calfresh")
    assert nc.matches_query("nc")
    assert not cal.matches_query("nc")
    assert cal.matches_query("california")
