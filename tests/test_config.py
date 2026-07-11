"""Settings validation (no LLM network calls)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.config import Settings, get_settings


def test_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
