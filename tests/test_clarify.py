"""Ambiguous yes/no detection and residency clarify copy."""

from __future__ import annotations

from src.state.clarify import clarify_residency_reply, is_ambiguous_yes_no


def test_ambiguous_yes_no_phrases() -> None:
    assert is_ambiguous_yes_no("maybe")
    assert is_ambiguous_yes_no("Maybe.")
    assert is_ambiguous_yes_no("not sure")
    assert is_ambiguous_yes_no("I don't know")
    assert is_ambiguous_yes_no("it depends")
    assert is_ambiguous_yes_no("kind of")
    assert is_ambiguous_yes_no("I split my time")


def test_clear_yes_no_not_ambiguous() -> None:
    assert not is_ambiguous_yes_no("yes")
    assert not is_ambiguous_yes_no("no")
    assert not is_ambiguous_yes_no("I live in California")
    assert not is_ambiguous_yes_no("yeah I do")


def test_clarify_residency_is_conversational() -> None:
    text = clarify_residency_reply("California")
    assert "California" in text
    assert "yes or no" in text.lower() or "yes or no" in text.lower()
    assert "Do you currently live in California?" not in text
