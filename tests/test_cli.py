"""CLI script runner (process_turn + Redis store stubbed)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.cli import _run_script, main
from src.config import get_settings
from src.process_turn import TurnResult
from src.state.models import EligibilityCase
from tests.conftest import FakeSessionStore

get_settings.cache_clear()


def _fake_process(message: str, case: EligibilityCase) -> TurnResult:
    case.turn_count += 1
    return TurnResult(reply=f"ok:{message}", case=case, safety_action="continue")


def test_run_script_skips_comments_and_blanks(tmp_path: Path) -> None:
    script = tmp_path / "demo.txt"
    script.write_text(
        "# comment\n\nfirst line\n# another\nsecond line\n",
        encoding="utf-8",
    )
    store = FakeSessionStore()
    sid = store.create()
    case = store.get(sid)
    calls: list[str] = []

    def tracking(message: str, c: EligibilityCase) -> TurnResult:
        calls.append(message)
        return _fake_process(message, c)

    with patch("src.cli.process_turn", side_effect=tracking):
        _run_script(str(script), case, store, sid, debug=False)

    assert calls == ["first line", "second line"]
    assert store.get(sid).turn_count == 2


def test_main_script_mode_exits_cleanly(tmp_path: Path) -> None:
    script = tmp_path / "one.txt"
    script.write_text("hello there\n", encoding="utf-8")
    store = FakeSessionStore()

    with (
        patch("src.cli.open_session_store", return_value=store),
        patch("src.cli.process_turn", side_effect=_fake_process),
    ):
        main(["--script", str(script)])


def test_main_missing_api_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    def boom() -> None:
        raise ValueError("OPENAI_API_KEY is required")

    with (
        patch("src.cli.get_settings", side_effect=boom),
        pytest.raises(SystemExit) as exc,
    ):
        main([])
    assert exc.value.code == 1
    get_settings.cache_clear()
    os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")


def test_main_redis_failure_exits() -> None:
    with (
        patch("src.cli.open_session_store", side_effect=ConnectionError("refused")),
        pytest.raises(SystemExit) as exc,
    ):
        main(["--script", "/dev/null"])
    assert exc.value.code == 1
