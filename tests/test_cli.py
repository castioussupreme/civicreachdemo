"""CLI as API client (HTTP stubbed)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:18080")

from src.api_client import AgentApiError
from src.cli import _run_script, main
from src.config import get_settings

get_settings.cache_clear()


def test_run_script_posts_each_line(tmp_path: Path) -> None:
    script = tmp_path / "demo.txt"
    script.write_text(
        "# comment\n\nfirst line\n# another\nsecond line\n",
        encoding="utf-8",
    )
    api = MagicMock()
    api.chat.side_effect = [
        {"session_id": "abc", "reply": "ok1", "assessment": None},
        {"session_id": "abc", "reply": "ok2", "assessment": None},
    ]
    _run_script(str(script), api, "abc", debug=False)
    assert api.chat.call_count == 2
    assert api.chat.call_args_list[0].args[0] == "first line"
    assert api.chat.call_args_list[1].args[0] == "second line"


def test_main_script_mode_exits_cleanly(tmp_path: Path) -> None:
    script = tmp_path / "one.txt"
    script.write_text("hello there\n", encoding="utf-8")
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = (
        "sid1",
        "Welcome",
        {"program_slug": "nc-fns", "ruleset_id": "nc-fns-screening-2025-10"},
    )
    api.list_programs.return_value = [
        {
            "slug": "nc-fns",
            "display_name": "NC FNS",
            "ruleset_id": "nc-fns-screening-2025-10",
            "effective_from": "2025-10-01",
            "effective_to": "2026-09-30",
            "search_aliases": [],
        }
    ]
    api.chat.return_value = {
        "session_id": "sid1",
        "reply": "hi",
        "assessment": None,
        "debug": None,
    }
    with (
        patch("src.cli.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.cli.AgentApiClient", return_value=api),
    ):
        main(["--script", str(script), "--program", "nc-fns"])
    api.close.assert_called()


def test_main_missing_api_base_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    with (
        patch("src.cli.resolve_public_api_base", side_effect=ValueError("no url")),
        pytest.raises(SystemExit) as exc,
    ):
        main([])
    assert exc.value.code == 1


def test_main_api_unreachable_exits() -> None:
    api = MagicMock()
    api.health.side_effect = AgentApiError("down")
    with (
        patch("src.cli.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.cli.AgentApiClient", return_value=api),
        pytest.raises(SystemExit) as exc,
    ):
        main([])
    assert exc.value.code == 1
