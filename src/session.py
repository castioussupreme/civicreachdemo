"""Redis-backed conversation sessions (session_id → EligibilityCase)."""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

import redis
from pydantic import ValidationError

from src.state.models import EligibilityCase, fresh_case

logger = logging.getLogger(__name__)

# Whole case (slots + transcript + assessment) lives under one Redis key.
# Sliding TTL: every write refreshes expiry. Idle sessions vanish entirely.
SESSION_TTL_SECONDS = 60 * 60 * 24  # 24 hours


class SessionNotFoundError(KeyError):
    """Session id missing or expired — client must create a session with a program."""


class SessionCorruptError(ValueError):
    """Stored case JSON failed validation — client should reset or start a new session."""


class SessionStoreProtocol(Protocol):
    def create(
        self,
        *,
        program_slug: str,
        as_of: str | None = None,
    ) -> str: ...

    def get(self, session_id: str) -> EligibilityCase: ...

    def set(self, session_id: str, case: EligibilityCase) -> None: ...

    def reset(
        self,
        session_id: str,
        *,
        program_slug: str,
        as_of: str | None = None,
    ) -> EligibilityCase: ...


class SessionStore:
    """
    Persist cases in Redis as JSON with a sliding TTL.

    Expiry deletes conversation history and structured case data together
    (single key `fns:case:{id}`). Missing/expired keys raise SessionNotFoundError
    — callers must create a session with an explicit program_slug.
    """

    def __init__(self, redis_url: str, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = "fns:case:"
        self._ttl_seconds = ttl_seconds

    def create(
        self,
        *,
        program_slug: str,
        as_of: str | None = None,
    ) -> str:
        if not (program_slug or "").strip():
            raise ValueError("program_slug is required")
        sid = str(uuid.uuid4())
        self.set(sid, fresh_case(program_slug=program_slug, as_of=as_of))
        return sid

    def get(self, session_id: str) -> EligibilityCase:
        raw = self._client.get(self._prefix + session_id)
        if raw is None:
            raise SessionNotFoundError(session_id)
        try:
            return EligibilityCase.model_validate_json(raw)
        except ValidationError as exc:
            logger.error("corrupt session %s: %s", session_id, exc)
            raise SessionCorruptError(session_id) from exc

    def set(self, session_id: str, case: EligibilityCase) -> None:
        # Re-validate before write so invalid in-memory values never hit Redis
        payload = case.model_dump_json()
        try:
            EligibilityCase.model_validate_json(payload)
        except ValidationError as exc:
            logger.error("refusing to persist invalid case for %s: %s", session_id, exc)
            raise SessionCorruptError(session_id) from exc
        self._client.set(
            self._prefix + session_id,
            payload,
            ex=self._ttl_seconds,
        )

    def reset(
        self,
        session_id: str,
        *,
        program_slug: str,
        as_of: str | None = None,
    ) -> EligibilityCase:
        if not (program_slug or "").strip():
            raise ValueError("program_slug is required")
        case = fresh_case(program_slug=program_slug, as_of=as_of)
        self.set(session_id, case)
        return case


def open_session_store(redis_url: str) -> SessionStore:
    return SessionStore(redis_url)
