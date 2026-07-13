"""Compose rails (disclaimer / terminal outcome) without calling the LLM."""

from __future__ import annotations

from src.compose.response import is_terminal_assessment, should_append_disclaimer
from src.limits import DEFAULT_MAX_MESSAGE_CHARS
from src.programs.registry import get_program
from src.state.models import (
    Assessment,
    AssessmentStatus,
    EligibilityCase,
    fresh_case,
)


def _assessment(status: AssessmentStatus) -> Assessment:
    return Assessment(
        status=status,
        reasons=["test"],
        rule_version="test",
        source_ids=["agent-disclaimer"],
    )


def test_terminal_statuses() -> None:
    assert is_terminal_assessment(_assessment(AssessmentStatus.LIKELY_ELIGIBLE))
    assert is_terminal_assessment(_assessment(AssessmentStatus.LIKELY_INELIGIBLE))
    assert is_terminal_assessment(_assessment(AssessmentStatus.UNABLE_TO_DETERMINE))
    assert not is_terminal_assessment(_assessment(AssessmentStatus.NEEDS_MORE_INFORMATION))
    assert not is_terminal_assessment(None)


def test_disclaimer_only_once_on_terminal() -> None:
    case = EligibilityCase()
    assert should_append_disclaimer(case, _assessment(AssessmentStatus.LIKELY_ELIGIBLE))
    assert not should_append_disclaimer(case, _assessment(AssessmentStatus.NEEDS_MORE_INFORMATION))
    case.disclaimer_given = True
    assert not should_append_disclaimer(case, _assessment(AssessmentStatus.LIKELY_ELIGIBLE))


def test_append_turn_trims_history() -> None:
    case = EligibilityCase()
    for i in range(30):
        case.append_turn("user", f"msg {i}")
    assert len(case.recent_turns) == 25
    assert case.recent_turns[0].text == "msg 5"


def test_append_turn_retention_cap_matches_default() -> None:
    """Safety net for retention (e.g. long assistant text); input oversize is rejected earlier."""
    case = EligibilityCase()
    long = "x" * (DEFAULT_MAX_MESSAGE_CHARS + 200)
    truncated = case.append_turn("assistant", long, max_chars=DEFAULT_MAX_MESSAGE_CHARS)
    assert truncated is True
    assert len(case.recent_turns[0].text) == DEFAULT_MAX_MESSAGE_CHARS
    assert case.recent_turns[0].text.endswith("...")


def test_fresh_case_has_opening() -> None:
    case = fresh_case(program_slug="nc-fns")
    assert len(case.recent_turns) == 1
    assert case.recent_turns[0].role == "assistant"
    assert "household" in case.recent_turns[0].text.lower()
    assert "income" in case.recent_turns[0].text.lower()
    assert case.last_question == get_program("nc-fns").opening_message
    assert case.program_slug == "nc-fns"
