"""Shared input / retention limits (single source of truth)."""

from __future__ import annotations

# Default for Settings.MAX_MESSAGE_CHARS and for tests that don't load custom env.
# Used for: user input acceptance, user transcript retention, soft assistant transcript cap.
DEFAULT_MAX_MESSAGE_CHARS = 1500

# Absolute ceiling so API clients cannot post multi-MB bodies even if misconfigured.
HARD_MAX_MESSAGE_CHARS = 100_000

# Placeholder stored in history instead of an oversized user paste.
LONG_MESSAGE_HISTORY_PLACEHOLDER = "[long message omitted — asked user to summarize]"

MESSAGE_TOO_LONG_REPLY = (
    "That message is longer than I can take in at once — I'm set up for short replies. "
    "Could you summarize the important bits?"
)
