"""Smoke runner unit tests (API client stubbed — no live network)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:18080")

from src.smoke import EXPECTED_MONTHLY, EXPECTED_STATUS, EXPECTED_THRESHOLD, run_smoke


def test_smoke_pass_with_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("hi\nI live in NC alone making 3000 monthly gross\n", encoding="utf-8")
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi")
    api.chat.return_value = {
        "session_id": "sid",
        "reply": "done",
        "stage": "assessed",
        "assessment": {
            "status": EXPECTED_STATUS.value,
            "household_size": 2,
            "normalized_gross_monthly": EXPECTED_MONTHLY,
            "threshold_used": EXPECTED_THRESHOLD,
        },
    }
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.smoke.AgentApiClient", return_value=api),
    ):
        assert run_smoke() == 0


def test_smoke_fails_without_assessment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("hello only\n", encoding="utf-8")
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi")
    api.chat.return_value = {
        "session_id": "sid",
        "reply": "more?",
        "stage": "collecting",
        "assessment": None,
    }
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.smoke.AgentApiClient", return_value=api),
    ):
        assert run_smoke() == 1


def test_smoke_fails_wrong_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("one\n", encoding="utf-8")
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi")
    api.chat.return_value = {
        "session_id": "sid",
        "reply": "nope",
        "assessment": {
            "status": "likely_ineligible",
            "household_size": 2,
            "normalized_gross_monthly": EXPECTED_MONTHLY,
            "threshold_used": EXPECTED_THRESHOLD,
        },
    }
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.smoke.AgentApiClient", return_value=api),
    ):
        assert run_smoke() == 1
