"""Shared fixtures: fake Redis session store for interface tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_REDIS_URL", "redis://localhost:6379/0")

from src.config import get_settings
from src.state.models import EligibilityCase


class FakeSessionStore:
    """In-test double only (production uses Redis exclusively)."""

    def __init__(self) -> None:
        self._sessions: dict[str, EligibilityCase] = {}

    def create(self) -> str:
        sid = str(uuid.uuid4())[:8]
        self._sessions[sid] = EligibilityCase()
        return sid

    def get(self, session_id: str) -> EligibilityCase:
        if session_id not in self._sessions:
            self._sessions[session_id] = EligibilityCase()
        return self._sessions[session_id]

    def set(self, session_id: str, case: EligibilityCase) -> None:
        self._sessions[session_id] = case

    def reset(self, session_id: str) -> EligibilityCase:
        case = EligibilityCase()
        self._sessions[session_id] = case
        return case


@pytest.fixture
def fake_session_store() -> Iterator[FakeSessionStore]:
    store = FakeSessionStore()
    with patch("src.api.app.open_session_store", return_value=store):
        yield store


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
