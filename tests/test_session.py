"""Redis session store (client faked; no in-memory production path)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.session import SESSION_TTL_SECONDS, SessionStore, open_session_store
from src.state.models import OPENING_MESSAGE, CaseField, EligibilityCase, FieldStatus, fresh_case


def test_open_session_store() -> None:
    with patch("src.session.redis.Redis.from_url") as from_url:
        client = MagicMock()
        from_url.return_value = client
        store = open_session_store("redis://localhost:6379/0")
        assert isinstance(store, SessionStore)
        from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)


def test_redis_round_trip() -> None:
    backend: dict[str, str] = {}
    client = MagicMock()

    def _get(key: str) -> str | None:
        return backend.get(key)

    def _set(key: str, value: str, **_kwargs: object) -> None:
        backend[key] = value

    client.get.side_effect = _get
    client.set.side_effect = _set

    with patch("src.session.redis.Redis.from_url", return_value=client):
        store = SessionStore("redis://localhost:6379/0")
        sid = store.create()
        case = store.get(sid)
        assert case.recent_turns
        assert case.recent_turns[0].text == OPENING_MESSAGE
        case.household_size = CaseField(status=FieldStatus.KNOWN, value=3)
        case.turn_count = 1
        store.set(sid, case)

        again = store.get(sid)
        assert again.household_size.value == 3
        assert again.turn_count == 1

        store.reset(sid)
        fresh = store.get(sid)
        assert fresh.household_size.value is None
        assert fresh.recent_turns[0].text == OPENING_MESSAGE


def test_redis_get_missing_key_initializes() -> None:
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = True

    with patch("src.session.redis.Redis.from_url", return_value=client):
        store = SessionStore("redis://localhost:6379/0")
        case = store.get("missing-id")
        assert isinstance(case, EligibilityCase)
        assert case.recent_turns[0].role == "assistant"
        assert client.set.called


def test_set_uses_sliding_ttl() -> None:
    """Session + conversation + case data share one key; set() refreshes TTL."""
    client = MagicMock()
    with patch("src.session.redis.Redis.from_url", return_value=client):
        store = SessionStore("redis://localhost:6379/0")
        store.set("abc123", fresh_case())
        assert client.set.called
        _args, kwargs = client.set.call_args
        assert kwargs.get("ex") == SESSION_TTL_SECONDS
        assert SESSION_TTL_SECONDS == 60 * 60 * 24
