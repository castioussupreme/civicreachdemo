"""
Line editor for the interactive CLI (arrows, history, word jumps).

Uses prompt_toolkit with *default* key bindings only. Custom Escape-prefix
bindings previously froze the second prompt (leftover Esc / multi-key wait).

Default Emacs mode already provides:
- Left / Right: move cursor
- Up / Down: history
- Ctrl+Left / Ctrl+Right (and Esc-b / Esc-f): word jumps
- Ctrl+A / Ctrl+E: line start / end

On macOS Terminal, enable \"Use Option as Meta key\" for Option+arrows as word jumps.
"""

from __future__ import annotations

import sys
from contextlib import suppress

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

_chat_history = InMemoryHistory()
_picker_history = InMemoryHistory()


def _history(kind: str) -> InMemoryHistory:
    if kind == "picker":
        return _picker_history
    return _chat_history


def read_line(message: str = "", *, history: str = "chat") -> str:
    """
    Read one line with full line editing.

    history: \"chat\" (main loop) or \"picker\" (program filter) — separate stacks.
    Raises EOFError / KeyboardInterrupt like input().
    """
    kind = history if history in {"chat", "picker"} else "chat"
    # Fresh session each call avoids sticky terminal/app state after Rich output.
    session: PromptSession[str] = PromptSession(
        history=_history(kind),
        enable_history_search=False,
        mouse_support=False,
        multiline=False,
    )
    # Flush anything Rich (or httpx) left buffered before taking over the TTY.
    for stream in (sys.stdout, sys.stderr):
        with suppress(Exception):
            stream.flush()
    # patch_stdout: safe if anything writes while the prompt is active
    with patch_stdout(raw=True):
        text = session.prompt(message)
    return text.strip()


def reset_histories_for_tests() -> None:
    """Clear in-memory history (unit tests only)."""
    global _chat_history, _picker_history  # noqa: PLW0603
    _chat_history = InMemoryHistory()
    _picker_history = InMemoryHistory()
