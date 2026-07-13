"""CLI program picker filter + display paging."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.cli import _PICKER_PAGE_SIZE, _catalog_item_matches, _pick_program


def _item(slug: str, name: str, *aliases: str) -> dict[str, object]:
    return {
        "slug": slug,
        "display_name": name,
        "search_aliases": list(aliases),
        "effective_to": "2026-09-30",
    }


def test_catalog_item_matches_short_token() -> None:
    nc = _item("nc-fns", "NC Food & Nutrition Services (SNAP)", "FNS", "food assistance")
    cal = _item("ca-calfresh", "California CalFresh (SNAP)", "CalFresh", "food assistance")
    assert _catalog_item_matches(nc, "nc")
    assert not _catalog_item_matches(cal, "nc")
    assert _catalog_item_matches(cal, "cal")
    assert _catalog_item_matches(nc, "nutrition")


def test_pick_program_filter_then_number() -> None:
    api = MagicMock()
    api.list_programs.return_value = [
        _item("ca-calfresh", "California CalFresh (SNAP)", "CalFresh"),
        _item("nc-fns", "NC Food & Nutrition Services (SNAP)", "FNS", "North Carolina"),
    ]
    inputs = iter(["nc", "1"])
    with (
        patch("src.cli.read_line", side_effect=lambda _m="", history="picker": next(inputs)),
        patch("src.cli.console") as cons,
    ):
        slug = _pick_program(api)
    assert slug == "nc-fns"
    printed = " ".join(str(c) for c in cons.print.call_args_list)
    assert "Filter:" in printed or "nc" in printed


def test_pick_program_shows_top_x_of_y_when_truncated() -> None:
    api = MagicMock()
    api.list_programs.return_value = [
        _item(f"prog-{i}", f"Program {i:02d} SNAP", "SNAP") for i in range(15)
    ]
    inputs = iter(["snap", "1"])
    with (
        patch("src.cli.read_line", side_effect=lambda _m="", history="picker": next(inputs)),
        patch("src.cli.console") as cons,
    ):
        slug = _pick_program(api)
    assert slug == "prog-0"
    printed = " ".join(str(c) for c in cons.print.call_args_list)
    assert f"top {_PICKER_PAGE_SIZE} of 15" in printed


def test_pick_program_clear_resets_filter() -> None:
    api = MagicMock()
    api.list_programs.return_value = [
        _item("ca-calfresh", "California CalFresh (SNAP)", "CalFresh"),
        _item("nc-fns", "NC Food & Nutrition Services (SNAP)", "FNS"),
    ]
    inputs = iter(["nc", "/clear", "1"])
    with patch("src.cli.read_line", side_effect=lambda _m="", history="picker": next(inputs)):
        slug = _pick_program(api)
    assert slug == "ca-calfresh"


def test_pick_program_invalid_number_does_not_become_filter() -> None:
    api = MagicMock()
    api.list_programs.return_value = [
        _item("ca-calfresh", "California CalFresh (SNAP)"),
        _item("nc-fns", "NC Food (SNAP)"),
    ]
    inputs = iter(["99", "2"])
    with patch("src.cli.read_line", side_effect=lambda _m="", history="picker": next(inputs)):
        slug = _pick_program(api)
    assert slug == "nc-fns"
