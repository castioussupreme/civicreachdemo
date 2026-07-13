"""Detect fuzzy yes/no answers and code-owned clarify copy."""

from __future__ import annotations

import re

# Soft / non-committal answers to a yes-no screening question
_AMBIGUOUS_YES_NO = re.compile(
    r"^\s*(?:"
    r"maybe|perhaps|possibly|probably|idk|i\s*don'?t\s*know|not\s*sure|"
    r"unsure|kind\s*of|sort\s*of|sometimes|it\s*depends|depends|"
    r"i\s*guess|ish|half\s*the\s*time|both|either|"
    r"not\s*really\s*sure|hard\s*to\s*say|complicated"
    r")[.!?\s]*$",
    re.IGNORECASE,
)

# Slightly longer hedges that still mean "not a clear yes/no"
_AMBIGUOUS_PHRASE = re.compile(
    r"\b(?:"
    r"not\s+sure|don'?t\s+know|no\s+idea|it\s+depends|kind\s+of|"
    r"sort\s+of|half\s+the\s+time|split\s+(?:my\s+)?time|"
    r"go\s+back\s+and\s+forth|a\s+few\s+months"
    r")\b",
    re.IGNORECASE,
)


def is_ambiguous_yes_no(message: str) -> bool:
    """True when the user did not clearly affirm or deny a yes/no question."""
    text = (message or "").strip()
    if not text or len(text) > 200:
        return False
    if _AMBIGUOUS_YES_NO.match(text):
        return True
    # Short message with a hedge phrase and no clear yes/no token
    if len(text) <= 80 and _AMBIGUOUS_PHRASE.search(text):
        lower = text.lower()
        return not bool(re.search(r"\b(yes|yeah|yep|yup|no|nope|nah)\b", lower))
    return False


def clarify_residency_reply(service_area: str) -> str:
    """Code-owned reply when residency is fuzzy — never re-paste the same yes/no."""
    area = (service_area or "").strip() or "the program service area"
    return (
        f"That's okay — it can be fuzzy. For this quick screen I only need a simple yes or no: "
        f"is your **main home right now** in {area} (where you live most of the time)? "
        f"If you split time between places, use the one you stay at most weeks."
    )
