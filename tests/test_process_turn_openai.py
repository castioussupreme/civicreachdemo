"""process_turn OpenAI failure paths (LLM raises mapped service errors)."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.openai_errors import OpenAIServiceError
from src.process_turn import process_turn
from src.state.models import EligibilityCase


def test_extract_quota_returns_friendly_reply() -> None:
    err = OpenAIServiceError(
        kind="quota",
        purpose="chat",
        user_message="I'm having trouble completing that right now.",
        log_message="quota log",
    )
    with patch("src.process_turn.extract_facts", side_effect=err):
        result = process_turn("I live in NC", EligibilityCase())
    assert result.safety_action == "service_unavailable"
    assert result.reply == "I'm having trouble completing that right now."
    assert "openai" not in result.reply.lower()
    assert result.debug.get("service_kind") == "quota"
    assert result.debug.get("service_phase") == "extract"
    assert result.case.recent_turns[-1].role == "assistant"


def test_compose_quota_returns_friendly_reply() -> None:
    err = OpenAIServiceError(
        kind="quota",
        purpose="chat",
        user_message="Something went wrong on my side.",
        log_message="compose log",
    )
    with (
        patch(
            "src.process_turn.extract_facts",
            return_value={"facts": {}, "user_intents": ["eligibility_screening"]},
        ),
        patch("src.process_turn.compose_response", side_effect=err),
    ):
        result = process_turn("hello", EligibilityCase())
    assert result.safety_action == "service_unavailable"
    assert result.reply == "Something went wrong on my side."
    assert result.debug.get("service_phase") == "compose"
