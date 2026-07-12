"""Shared fixtures: fake Redis session store + RAG stubs for unit tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PUBLIC_QDRANT_URL", "http://127.0.0.1:6333")
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")

from src.config import get_settings
from src.state.models import EligibilityCase, fresh_case


class FakeSessionStore:
    """In-test double only (production uses Redis exclusively)."""

    def __init__(self) -> None:
        self._sessions: dict[str, EligibilityCase] = {}

    def create(self) -> str:
        sid = str(uuid.uuid4())[:8]
        self._sessions[sid] = fresh_case()
        return sid

    def get(self, session_id: str) -> EligibilityCase:
        if session_id not in self._sessions:
            self._sessions[session_id] = fresh_case()
        return self._sessions[session_id]

    def set(self, session_id: str, case: EligibilityCase) -> None:
        self._sessions[session_id] = case

    def reset(self, session_id: str) -> EligibilityCase:
        case = fresh_case()
        self._sessions[session_id] = case
        return case


@pytest.fixture
def fake_session_store() -> Iterator[FakeSessionStore]:
    store = FakeSessionStore()
    with (
        patch("src.api.app.open_session_store", return_value=store),
        patch("src.api.app.ensure_index", return_value=None),
    ):
        yield store


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_vector_rag() -> Iterator[None]:
    """
    Unit tests must not call live OpenAI embeddings or Qdrant.
    Individual retrieval tests re-patch these as needed.
    """
    with (
        patch("src.retrieval.retrieve.ensure_index", return_value=None),
        patch("src.retrieval.retrieve.embed_query", return_value=[0.01] * 8),
        patch("src.retrieval.retrieve.make_client", return_value=MagicMock()),
        patch("src.retrieval.retrieve.search", return_value=[]),
        patch("src.api.app.ensure_index", return_value=None),
    ):
        yield
