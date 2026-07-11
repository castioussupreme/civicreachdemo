from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class SafetyAction(StrEnum):
    CONTINUE = "continue"
    CRISIS = "crisis"
    REFUSE_SCOPE = "refuse_scope"
    REFUSE_APPLICATION = "refuse_application"
    PII_WARN = "pii_warn"  # continue after warning
    INJECTION_NOTICE = "injection_notice"  # continue, ignore instructions


@dataclass
class SafetyResult:
    action: SafetyAction
    reasons: list[str] = field(default_factory=list)
    user_message: str | None = None
    redacted_message: str | None = None
    continue_after_warning: bool = False


CRISIS_PATTERNS = [
    r"\b(kill myself|suicide|suicidal|end my life|want to die)\b",
    r"\b(self[-\s]?harm|cutting myself)\b",
    r"\b(going to hurt myself)\b",
]

APPLICATION_PATTERNS = [
    r"\b(submit|file|send)\b.{0,40}\b(application|app)\b",
    r"\bapply\s+(for\s+me|on\s+my\s+behalf)\b",
    r"\b(log\s*in|login).{0,20}\b(epass|dss)\b",
]

OUT_OF_SCOPE_PATTERNS = [
    r"\b(medicaid|medicare|section\s*8|housing\s+voucher|wic|liheap|tanf\s+application)\b",
    r"\b(legal\s+advice|sue|lawsuit|immigration\s+lawyer)\b",
    r"\b(medical\s+advice|diagnos(e|is)|prescription)\b",
    r"\b(write\s+(me\s+)?malware|hack\b|exploit)\b",
]

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(your\s+)?(system|prior)\s+(prompt|instructions)",
    r"you\s+are\s+now\s+(dan|jailbroken|unrestricted)",
    r"reveal\s+(your\s+)?(system\s+prompt|hidden\s+instructions)",
    r"pretend\s+you\s+have\s+no\s+rules",
]

# SSN patterns (xxx-xx-xxxx or 9 consecutive digits in SSN-like context)
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?<!\$)\d{9}\b")
# Rough full street address (number + street word)
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+\w+(?:\s\w+){0,3}\s+(street|st|avenue|ave|road|rd|blvd|lane|ln|drive|dr)\b",
    re.I,
)

CRISIS_RESPONSE = (
    "I'm concerned about your safety. I'm not able to help with crisis situations, "
    "but real people can.\n\n"
    "- If you are in immediate danger, call **911**.\n"
    "- National Suicide & Crisis Lifeline: call or text **988** (US).\n"
    "- https://988lifeline.org/\n\n"
    "I won't continue eligibility screening right now. Please reach out for support."
)

APPLICATION_RESPONSE = (
    "I can't submit applications, contact DSS, or log into government systems. "
    "I'm only an informal screening assistant.\n\n"
    "You can apply yourself via **NC ePASS** (https://epass.nc.gov/) or your local "
    "county Department of Social Services. If you want, I can keep helping you "
    "understand whether you *might* qualify based on public rules."
)

SCOPE_RESPONSE = (
    "That request is outside what I can help with. I only provide informal screening "
    "information about **North Carolina FNS (SNAP food assistance)** based on public "
    "eligibility documents.\n\n"
    "For other benefits or emergencies, try dialing **211** or contacting the "
    "appropriate agency. If you want to check likely FNS eligibility, tell me about "
    "your household and income."
)

INJECTION_RESPONSE = (
    "I can't change my operating rules or ignore safety constraints. "
    "I'll continue only as an NC FNS screening assistant using fixed eligibility "
    "rules and curated public documents.\n\n"
    "If you're here about food assistance eligibility, share what you're comfortable "
    "sharing about household size and income (no SSN or full address needed)."
)

PII_RESPONSE = (
    "Please don't share Social Security numbers, full street addresses, or other "
    "sensitive identifiers here. I don't need them for a likelihood screen, and I "
    "won't store them.\n\n"
    "You can continue with general facts only (for example household size and "
    "approximate income)."
)


def redact_pii(message: str) -> tuple[str, bool]:
    found = False
    out = message
    if SSN_PATTERN.search(out):
        found = True
        out = SSN_PATTERN.sub("[REDACTED-SSN]", out)
    if ADDRESS_PATTERN.search(out):
        found = True
        out = ADDRESS_PATTERN.sub("[REDACTED-ADDRESS]", out)
    return out, found


def check_safety(message: str) -> SafetyResult:
    text = message.strip()
    lower = text.lower()

    for pat in CRISIS_PATTERNS:
        if re.search(pat, lower):
            return SafetyResult(
                action=SafetyAction.CRISIS,
                reasons=["crisis_language"],
                user_message=CRISIS_RESPONSE,
            )

    for pat in APPLICATION_PATTERNS:
        if re.search(pat, lower):
            return SafetyResult(
                action=SafetyAction.REFUSE_APPLICATION,
                reasons=["application_request"],
                user_message=APPLICATION_RESPONSE,
                continue_after_warning=False,
            )

    # Application refusal is terminal for that turn but user can continue later;
    # we still return refuse so processTurn can show message. If message *also*
    # has eligibility content after refusal, caller may choose to continue.
    # Keep simple: refuse_application stops this turn unless message clearly
    # also answers eligibility — handled in process_turn.

    for pat in OUT_OF_SCOPE_PATTERNS:
        if re.search(pat, lower):
            # Allow if primary intent is still FNS and mention is incidental
            if re.search(r"\b(fns|snap|food\s+stamp|food\s+assistance|eligib)", lower):
                continue
            return SafetyResult(
                action=SafetyAction.REFUSE_SCOPE,
                reasons=["out_of_scope"],
                user_message=SCOPE_RESPONSE,
            )

    injection_hit = any(re.search(pat, lower) for pat in INJECTION_PATTERNS)
    redacted, pii_found = redact_pii(text)

    if injection_hit and pii_found:
        return SafetyResult(
            action=SafetyAction.INJECTION_NOTICE,
            reasons=["prompt_injection", "pii"],
            user_message=INJECTION_RESPONSE + "\n\n" + PII_RESPONSE,
            redacted_message=redacted,
            continue_after_warning=True,
        )

    if injection_hit:
        return SafetyResult(
            action=SafetyAction.INJECTION_NOTICE,
            reasons=["prompt_injection"],
            user_message=INJECTION_RESPONSE,
            redacted_message=redacted,
            continue_after_warning=True,
        )

    if pii_found:
        return SafetyResult(
            action=SafetyAction.PII_WARN,
            reasons=["pii_detected"],
            user_message=PII_RESPONSE,
            redacted_message=redacted,
            continue_after_warning=True,
        )

    return SafetyResult(
        action=SafetyAction.CONTINUE,
        reasons=[],
        redacted_message=text,
    )
