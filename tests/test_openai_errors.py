"""OpenAI error mapping (no network)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from openai import APIStatusError, AuthenticationError, RateLimitError
from src.openai_errors import OpenAIServiceError, log_service_error, map_openai_error


def _rate_limit(*, code: str | None = None, message: str = "rate limited") -> RateLimitError:
    body: dict[str, object] = {"error": {"message": message, "type": "rate_limit_error"}}
    if code is not None:
        err = body["error"]
        assert isinstance(err, dict)
        err["code"] = code
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    resp.json.return_value = body
    return RateLimitError(message, response=resp, body=body)


def _assert_user_message_is_public(msg: str) -> None:
    lowered = msg.lower()
    forbidden = (
        "openai",
        "api key",
        "api_key",
        ".env",
        "billing",
        "platform.openai",
        "scope",
        "model.request",
        "make index",
        "qdrant",
    )
    for token in forbidden:
        assert token not in lowered, f"user message must not contain {token!r}: {msg}"


def test_maps_insufficient_quota_chat() -> None:
    exc = _rate_limit(code="insufficient_quota", message="You exceeded your current quota")
    mapped = map_openai_error(exc, purpose="chat")
    assert mapped.kind == "quota"
    _assert_user_message_is_public(mapped.user_message)
    assert "try again" in mapped.user_message.lower() or "later" in mapped.user_message.lower()


def test_maps_insufficient_quota_embeddings() -> None:
    exc = _rate_limit(code="insufficient_quota", message="You exceeded your current quota")
    mapped = map_openai_error(exc, purpose="embeddings")
    assert mapped.kind == "quota"
    _assert_user_message_is_public(mapped.user_message)


def test_maps_generic_rate_limit() -> None:
    exc = _rate_limit(message="Too many requests")
    mapped = map_openai_error(exc, purpose="chat")
    assert mapped.kind == "rate_limit"
    _assert_user_message_is_public(mapped.user_message)
    assert "try again" in mapped.user_message.lower() or "wait" in mapped.user_message.lower()


def test_maps_auth() -> None:
    resp = MagicMock()
    resp.status_code = 401
    resp.headers = {}
    body = {"error": {"message": "invalid api key", "type": "invalid_request_error"}}
    resp.json.return_value = body
    exc = AuthenticationError("invalid", response=resp, body=body)
    mapped = map_openai_error(exc, purpose="chat")
    assert mapped.kind == "auth"
    _assert_user_message_is_public(mapped.user_message)
    assert "invalid_request_error" not in mapped.log_message
    assert mapped.raw_detail


def test_maps_missing_scope() -> None:
    resp = MagicMock()
    resp.status_code = 401
    resp.headers = {}
    body = {
        "error": {
            "message": "Missing scopes: model.request",
            "type": "invalid_request_error",
            "code": "missing_scope",
        }
    }
    resp.json.return_value = body
    exc = APIStatusError("missing", response=resp, body=body)
    mapped = map_openai_error(exc, purpose="chat")
    assert mapped.kind == "auth"
    _assert_user_message_is_public(mapped.user_message)
    assert "model.request" not in mapped.user_message


def test_log_service_error_includes_raw_detail(caplog: pytest.LogCaptureFixture) -> None:
    err = OpenAIServiceError(
        kind="quota",
        purpose="chat",
        user_message="friendly",
        log_message="operator short",
        raw_detail="Error code: 429 - full provider body",
    )
    with caplog.at_level(logging.ERROR, logger="src.openai_errors"):
        log_service_error(err, where="chat_json")
    text = "\n".join(caplog.messages)
    assert "operator short" in text
    assert "full provider body" in text
    assert "friendly" not in text or "full provider" in text


def test_maps_status_429_quota_message() -> None:
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    resp.json.return_value = body
    exc = APIStatusError("quota", response=resp, body=body)
    mapped = map_openai_error(exc, purpose="chat")
    assert mapped.kind == "quota"
    _assert_user_message_is_public(mapped.user_message)
