"""
Safety resolution: LLM confidence primary, regex fallback.

Dual rule for every signal:
  - If extract reports confidence >= THRESHOLD -> trust the LLM flag.
  - Else (missing / low confidence) -> use regex detector as fallback.
Regex patterns are intentionally NARROW (clear-cut phrases only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict

from src.extraction.schema import ExtractionResult


class SafetyAction(StrEnum):
    CONTINUE = "continue"
    CRISIS = "crisis"
    REFUSE_SCOPE = "refuse_scope"
    REFUSE_APPLICATION = "refuse_application"
    PII_WARN = "pii_warn"
    INJECTION_NOTICE = "injection_notice"
    STEER_OFF_TOPIC = "steer_off_topic"


@dataclass
class SafetyResult:
    action: SafetyAction
    reasons: list[str] = field(default_factory=list)
    user_message: str | None = None
    redacted_message: str | None = None
    continue_after_warning: bool = False
    # Debug: which source won for the chosen action
    source: str = ""  # "llm" | "regex_fallback" | "none"


# Confidence at/above this: trust the model flag (true or false).
LLM_CONFIDENCE_THRESHOLD = 0.7

# --- Regex fallback: ONLY high-precision, unambiguous phrases ---
# Greyer cases (soft scope, jokes, vague injection, bare digits) rely on LLM.

# Explicit self-harm / suicide language (life-safety fail-closed)
CRISIS_PATTERNS = [
    r"\b(kill myself|commit suicide|end my life)\b",
    r"\bsuicid(e|al)\b",
    r"\bwant to die\b",
]

# Unambiguous "you apply for me" — not "how do I apply"
APPLICATION_PATTERNS = [
    r"\bapply\s+for\s+me\b",
    r"\bapply\s+on\s+my\s+behalf\b",
    r"\bsubmit\s+(my|an|the)\s+application\s+for\s+me\b",
    r"\bsubmit\s+(my|an|the)\s+application\b.{0,40}\bfor\s+me\b",
    r"\b(log\s*in|login)\s+(to\s+)?(epass|benefitscal)\s+for\s+me\b",
]

# out_of_scope + off_topic: LLM-only (too semantic for safe regex fallback)

# Classic jailbreak phrases only
INJECTION_PATTERNS = [
    r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b",
    r"\bdisregard\s+(your\s+)?(system|prior)\s+(prompt|instructions)\b",
    r"\byou\s+are\s+now\s+(dan|jailbroken)\b",
    r"\breveal\s+(your\s+)?system\s+prompt\b",
]

# Clear SSN form only (not bare 9 digits)
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Number + full street type word
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+){0,3}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b",
    re.I,
)

CRISIS_RESPONSE = (
    "I'm really glad you said something — I'm not the right support for a crisis, "
    "but people who can help are a call or text away.\n\n"
    "If you're in immediate danger, call **911**. In the US you can also call or text "
    "**988** (Suicide & Crisis Lifeline): https://988lifeline.org/\n\n"
    "I'll pause the eligibility chat for now. Please reach out to them."
)

APPLICATION_RESPONSE = (
    "I can't submit an application or log into government systems for you — only you "
    "(or someone you authorize with the agency) can do that."
)

PII_RESPONSE = (
    "Please skip SSNs and full street addresses — I don't need them for this check and "
    "won't keep them."
)


class _Signal(TypedDict):
    flag: bool
    confidence: float


def injection_notice(program_label: str) -> str:
    return (
        f"I can't change how I work or ignore those limits — "
        f"I'll stick to a simple {program_label} screen."
    )


def scope_notice(program_label: str) -> str:
    return (
        f"That's outside what I can help with — I only do a simple {program_label} "
        f"likelihood check (not other benefits, legal, or medical advice)."
    )


def off_topic_notice(program_label: str) -> str:
    return f"I can't answer things not related to {program_label}."


def redact_pii(message: str) -> tuple[str, bool]:
    """Mechanical scrub for storage / logs (always available)."""
    found = False
    out = message
    if SSN_PATTERN.search(out):
        found = True
        out = SSN_PATTERN.sub("[REDACTED-SSN]", out)
    if ADDRESS_PATTERN.search(out):
        found = True
        out = ADDRESS_PATTERN.sub("[REDACTED-ADDRESS]", out)
    return out, found


def _any_pattern(patterns: list[str], text: str) -> bool:
    return any(re.search(pat, text) for pat in patterns)


def _regex_signals(message: str) -> dict[str, bool]:
    """High-precision fallback only — not a general classifier."""
    lower = message.strip().lower()
    return {
        "crisis": _any_pattern(CRISIS_PATTERNS, lower),
        "request_apply_for_me": _any_pattern(APPLICATION_PATTERNS, lower),
        # No regex for out_of_scope / off_topic — LLM confidence only
        "out_of_scope": False,
        "off_topic": False,
        "prompt_injection": _any_pattern(INJECTION_PATTERNS, lower),
        "pii": redact_pii(message)[1],
    }


def _llm_signal(safety: object, key: str) -> _Signal | None:
    if not isinstance(safety, dict):
        return None
    raw = safety.get(key)
    if not isinstance(raw, dict):
        return None
    flag = bool(raw.get("flag"))
    conf_raw = raw.get("confidence")
    try:
        conf = float(conf_raw) if conf_raw is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {"flag": flag, "confidence": conf}


def _decide(llm: _Signal | None, regex_hit: bool) -> tuple[bool, str]:
    """
    Dual decision: high-confidence LLM wins; otherwise regex fallback.
    Returns (active, source).
    """
    if llm is not None and llm["confidence"] >= LLM_CONFIDENCE_THRESHOLD:
        return llm["flag"], "llm"
    return regex_hit, "regex_fallback" if regex_hit else "none"


def resolve_safety(
    message: str,
    extraction: ExtractionResult | None = None,
) -> SafetyResult:
    """
    Primary: extraction.safety.* with confidence.
    Fallback: narrow regex detectors when confidence is low or missing.
    """
    text = message.strip()
    redacted, regex_pii = redact_pii(text)
    regex = _regex_signals(text)
    safety_block = extraction.get("safety") if extraction else None

    ordered: list[tuple[str, SafetyAction]] = [
        ("crisis", SafetyAction.CRISIS),
        ("request_apply_for_me", SafetyAction.REFUSE_APPLICATION),
        ("out_of_scope", SafetyAction.REFUSE_SCOPE),
        ("off_topic", SafetyAction.STEER_OFF_TOPIC),
        ("prompt_injection", SafetyAction.INJECTION_NOTICE),
        ("pii", SafetyAction.PII_WARN),
    ]

    hits: dict[str, tuple[bool, str]] = {}
    for key, _action in ordered:
        llm = _llm_signal(safety_block, key)
        active, source = _decide(llm, regex.get(key, False))
        hits[key] = (active, source)

    active, source = hits["crisis"]
    if active:
        return SafetyResult(
            action=SafetyAction.CRISIS,
            reasons=["crisis_language", f"source:{source}"],
            user_message=CRISIS_RESPONSE,
            redacted_message=redacted if regex_pii else text,
            source=source,
        )

    active, source = hits["request_apply_for_me"]
    if active:
        return SafetyResult(
            action=SafetyAction.REFUSE_APPLICATION,
            reasons=["application_request", f"source:{source}"],
            user_message=APPLICATION_RESPONSE,
            redacted_message=redacted if regex_pii else text,
            continue_after_warning=False,
            source=source,
        )

    active, source = hits["out_of_scope"]
    if active:
        return SafetyResult(
            action=SafetyAction.REFUSE_SCOPE,
            reasons=["out_of_scope", f"source:{source}"],
            user_message=None,
            redacted_message=redacted if regex_pii else text,
            continue_after_warning=True,
            source=source,
        )

    active, source = hits["off_topic"]
    if active:
        return SafetyResult(
            action=SafetyAction.STEER_OFF_TOPIC,
            reasons=["off_topic", f"source:{source}"],
            user_message=None,
            redacted_message=redacted if regex_pii else text,
            continue_after_warning=True,
            source=source,
        )

    inj_active, inj_source = hits["prompt_injection"]
    pii_active, pii_source = hits["pii"]
    do_redact = regex_pii or pii_active
    out_text = redacted if do_redact else text

    if inj_active and pii_active:
        return SafetyResult(
            action=SafetyAction.INJECTION_NOTICE,
            reasons=["prompt_injection", "pii", f"source:{inj_source}"],
            user_message=None,
            redacted_message=out_text,
            continue_after_warning=True,
            source=inj_source,
        )
    if inj_active:
        return SafetyResult(
            action=SafetyAction.INJECTION_NOTICE,
            reasons=["prompt_injection", f"source:{inj_source}"],
            user_message=None,
            redacted_message=out_text,
            continue_after_warning=True,
            source=inj_source,
        )
    if pii_active:
        return SafetyResult(
            action=SafetyAction.PII_WARN,
            reasons=["pii_detected", f"source:{pii_source}"],
            user_message=PII_RESPONSE,
            redacted_message=out_text,
            continue_after_warning=True,
            source=pii_source,
        )

    return SafetyResult(
        action=SafetyAction.CONTINUE,
        reasons=[],
        redacted_message=out_text,
        source="none",
    )


def check_safety(message: str) -> SafetyResult:
    """
    Regex-only fallback path (no extraction). Used when extract fails or in unit tests
    that only exercise detectors. Prefer resolve_safety(message, extraction) in the pipeline.
    """
    return resolve_safety(message, extraction=None)


def personalize_safety_notice(
    action: SafetyAction,
    *,
    program_label: str,
    base_message: str | None = None,
) -> str | None:
    """Fill program-specific refuse/steer lines."""
    if action == SafetyAction.INJECTION_NOTICE:
        notice = injection_notice(program_label)
        if base_message and ("pii" in base_message.lower() or "[REDACTED" in base_message):
            return notice + " " + PII_RESPONSE
        return notice
    if action == SafetyAction.REFUSE_SCOPE:
        return scope_notice(program_label)
    if action == SafetyAction.STEER_OFF_TOPIC:
        return off_topic_notice(program_label)
    if action == SafetyAction.REFUSE_APPLICATION:
        return APPLICATION_RESPONSE
    if action == SafetyAction.PII_WARN:
        return PII_RESPONSE
    if action == SafetyAction.CRISIS:
        return CRISIS_RESPONSE
    return base_message
