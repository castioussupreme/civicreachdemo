"""Settings validation (no LLM network calls)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.config import Settings, get_settings


def test_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Empty env wins over .env file values
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
    get_settings.cache_clear()


def test_strips_and_accepts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-test  ")
    get_settings.cache_clear()
    s = get_settings()
    assert s.openai_api_key == "sk-test"
    get_settings.cache_clear()


def test_max_message_chars_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "2000")
    get_settings.cache_clear()
    s = get_settings()
    assert s.max_message_chars == 2000
    get_settings.cache_clear()
