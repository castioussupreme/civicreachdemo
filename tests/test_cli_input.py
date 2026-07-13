"""CLI line editor helpers (no TTY interaction)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.cli_input import read_line, reset_histories_for_tests


def test_read_line_uses_prompt_session_and_strips() -> None:
    reset_histories_for_tests()
    session = MagicMock()
    session.prompt.return_value = "  hello  "
    with (
        patch("src.cli_input.PromptSession", return_value=session) as ps,
        patch("src.cli_input.patch_stdout"),
    ):
        assert read_line("You> ", history="chat") == "hello"
    ps.assert_called_once()
    session.prompt.assert_called_once_with("You> ")


def test_read_line_picker_uses_picker_history() -> None:
    reset_histories_for_tests()
    session = MagicMock()
    session.prompt.return_value = "nc"
    with (
        patch("src.cli_input.PromptSession", return_value=session) as ps,
        patch("src.cli_input.patch_stdout"),
    ):
        assert read_line("Filter / number> ", history="picker") == "nc"
    kwargs = ps.call_args.kwargs
    assert kwargs["history"] is not None
