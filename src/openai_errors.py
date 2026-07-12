"""Map OpenAI SDK failures to operator logs + generic user-facing copy."""

from __future__ import annotations

import logging
from typing import Literal

from openai import APIError, APIStatusError, AuthenticationError, OpenAIError, RateLimitError

Purpose = Literal["chat", "embeddings"]

_service_logger = logging.getLogger("src.openai_errors")


class OpenAIServiceError(Exception):
    """Service failure; user_message is safe for clients (no vendor/key details)."""

    def __init__(
        self,
        *,
        kind: str,
        purpose: Purpose,
        user_message: str,
        log_message: str,
        raw_detail: str = "",
    ) -> None:
        super().__init__(log_message)
        self.kind = kind
        self.purpose = purpose
        self.user_message = user_message
        self.log_message = log_message
        # Full SDK text — DEBUG / operator only, never user-facing
        self.raw_detail = raw_detail


# --- User-facing (CLI + API clients): no vendor, keys, env, or ops commands ---

_CHAT_QUOTA = (
    "I'm having trouble completing that right now because the service is temporarily "
    "unavailable. Please try again later."
)

_CHAT_RATE = "I'm a bit overloaded at the moment. Please wait a few seconds and try again."

_CHAT_AUTH = (
    "I'm not able to complete that request right now. Please try again later, "
    "or contact the person who runs this service if the problem continues."
)

_CHAT_SCOPE = _CHAT_AUTH

_CHAT_OTHER = "Something went wrong on my side. Please try again in a moment."

# Embeddings user_message is rarely shown to end users; keep equally generic
# if it ever surfaces via a client.
_EMBED_QUOTA = _CHAT_QUOTA
_EMBED_RATE = _CHAT_RATE
_EMBED_AUTH = _CHAT_AUTH
_EMBED_SCOPE = _CHAT_AUTH
_EMBED_OTHER = _CHAT_OTHER


def _code_from_error(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            c = err.get("code")
            if isinstance(c, str):
                return c
    return None


def _is_quota(exc: BaseException) -> bool:
    code = (_code_from_error(exc) or "").lower()
    msg = str(exc).lower()
    return (
        code == "insufficient_quota"
        or "insufficient_quota" in msg
        or "exceeded your current quota" in msg
        or ("billing" in msg and "quota" in msg)
    )


def _is_missing_scope(exc: BaseException) -> bool:
    code = (_code_from_error(exc) or "").lower()
    msg = str(exc).lower()
    return code == "missing_scope" or "missing scopes" in msg or "missing_scope" in msg


def _short_ref(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    code = _code_from_error(exc)
    parts: list[str] = [type(exc).__name__]
    if status is not None:
        parts.append(f"status={status}")
    if code:
        parts.append(f"code={code}")
    return " ".join(parts)


def map_openai_error(exc: BaseException, *, purpose: Purpose) -> OpenAIServiceError:
    """Turn an OpenAI SDK exception into a typed error (generic user_message)."""
    raw = str(exc)
    short = _short_ref(exc)

    if purpose == "chat":
        quota_msg, rate_msg, auth_msg, scope_msg, other_msg = (
            _CHAT_QUOTA,
            _CHAT_RATE,
            _CHAT_AUTH,
            _CHAT_SCOPE,
            _CHAT_OTHER,
        )
    else:
        quota_msg, rate_msg, auth_msg, scope_msg, other_msg = (
            _EMBED_QUOTA,
            _EMBED_RATE,
            _EMBED_AUTH,
            _EMBED_SCOPE,
            _EMBED_OTHER,
        )

    if _is_missing_scope(exc):
        return OpenAIServiceError(
            kind="auth",
            purpose=purpose,
            user_message=scope_msg,
            log_message=f"OpenAI permission/scope error ({purpose}): {short}",
            raw_detail=raw,
        )

    if isinstance(exc, AuthenticationError):
        return OpenAIServiceError(
            kind="auth",
            purpose=purpose,
            user_message=auth_msg,
            log_message=f"OpenAI auth error ({purpose}): {short}",
            raw_detail=raw,
        )

    if isinstance(exc, RateLimitError) or (
        isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 429
    ):
        if _is_quota(exc):
            return OpenAIServiceError(
                kind="quota",
                purpose=purpose,
                user_message=quota_msg,
                log_message=f"OpenAI quota exceeded ({purpose}): {short}",
                raw_detail=raw,
            )
        return OpenAIServiceError(
            kind="rate_limit",
            purpose=purpose,
            user_message=rate_msg,
            log_message=f"OpenAI rate limited ({purpose}): {short}",
            raw_detail=raw,
        )

    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) in {401, 403}:
        user = scope_msg if _is_missing_scope(exc) else auth_msg
        return OpenAIServiceError(
            kind="auth",
            purpose=purpose,
            user_message=user,
            log_message=f"OpenAI status error ({purpose}): {short}",
            raw_detail=raw,
        )

    if isinstance(exc, APIError | OpenAIError):
        if _is_quota(exc):
            return OpenAIServiceError(
                kind="quota",
                purpose=purpose,
                user_message=quota_msg,
                log_message=f"OpenAI quota-like error ({purpose}): {short}",
                raw_detail=raw,
            )
        return OpenAIServiceError(
            kind="api_error",
            purpose=purpose,
            user_message=other_msg,
            log_message=f"OpenAI API error ({purpose}): {short}",
            raw_detail=raw,
        )

    return OpenAIServiceError(
        kind="unknown",
        purpose=purpose,
        user_message=other_msg,
        log_message=f"OpenAI unexpected error ({purpose}): {short}",
        raw_detail=raw,
    )


def log_service_error(mapped: OpenAIServiceError, *, where: str = "") -> None:
    """
    Emit full operator detail for the backend service logs.

    Includes kind/purpose and the raw SDK body. Safe for Docker/uvicorn;
    CLI/smoke silence these loggers via configure_client_logging.
    """
    prefix = f"{where}: " if where else ""
    _service_logger.error("%s%s", prefix, mapped.log_message)
    if mapped.raw_detail:
        _service_logger.error("%sfull provider error: %s", prefix, mapped.raw_detail)


def reraise_openai(exc: BaseException, *, purpose: Purpose) -> None:
    """Always raises OpenAIServiceError (never returns)."""
    raise map_openai_error(exc, purpose=purpose) from exc
