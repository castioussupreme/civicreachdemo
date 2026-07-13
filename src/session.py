"""Redis-backed conversation sessions (session_id → EligibilityCase)."""

from __future__ import annotations

import uuid
from typing import Protocol

import redis

from src.state.models import EligibilityCase, fresh_case

# Whole case (slots + transcript + assessment) lives under one Redis key.
# Sliding TTL: every write refreshes expiry. Idle sessions vanish entirely.
SESSION_TTL_SECONDS = 60 * 60 * 24  # 24 hours


class SessionStoreProtocol(Protocol):
    def create(
        self,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> str: ...

    def get(self, session_id: str) -> EligibilityCase: ...

    def set(self, session_id: str, case: EligibilityCase) -> None: ...

    def reset(
        self,
        session_id: str,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> EligibilityCase: ...


class SessionStore:
    """
    Persist cases in Redis as JSON with a sliding TTL.

    Expiry deletes conversation history and structured case data together
    (single key `fns:case:{id}`). After expiry, get() starts a fresh case.
    """

    def __init__(self, redis_url: str, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = "fns:case:"
        self._ttl_seconds = ttl_seconds

    def create(
        self,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> str:
        sid = str(uuid.uuid4())[:8]
        self.set(sid, fresh_case(program_slug=program_slug, as_of=as_of))
        return sid

    def get(self, session_id: str) -> EligibilityCase:
        raw = self._client.get(self._prefix + session_id)
        if raw is None:
            # Missing or expired key → new empty screening session
            case = fresh_case()
            self.set(session_id, case)
            return case
        return EligibilityCase.model_validate_json(raw)

    def set(self, session_id: str, case: EligibilityCase) -> None:
        self._client.set(
            self._prefix + session_id,
            case.model_dump_json(),
            ex=self._ttl_seconds,
        )

    def reset(
        self,
        session_id: str,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> EligibilityCase:
        case = fresh_case(program_slug=program_slug, as_of=as_of)
        self.set(session_id, case)
        return case


def open_session_store(redis_url: str) -> SessionStore:
    return SessionStore(redis_url)
