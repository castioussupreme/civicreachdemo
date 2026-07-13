"""Agnostic program registry / catalog (multi-pack infrastructure)."""

from __future__ import annotations

from datetime import date

from src.programs.registry import catalog_programs, list_enabled_slugs


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
