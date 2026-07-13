from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from src.json_types import JsonObject, JsonValue
from src.limits import DEFAULT_MAX_MESSAGE_CHARS
from src.programs.registry import get_program, resolve_ruleset

T = TypeVar("T")

# Values that may appear in case fields / contradiction logs
ScalarValue = bool | int | float | str


class FieldStatus(StrEnum):
    UNKNOWN = "unknown"
    KNOWN = "known"
    UNCERTAIN = "uncertain"
    CONFLICTING = "conflicting"


class Stage(StrEnum):
    INTRODUCTION = "introduction"
    COLLECTING = "collecting"
    CLARIFYING = "clarifying"
    READY_TO_ASSESS = "ready_to_assess"
    ASSESSED = "assessed"


class AssessmentStatus(StrEnum):
    LIKELY_ELIGIBLE = "likely_eligible"
    LIKELY_INELIGIBLE = "likely_ineligible"
    NEEDS_MORE_INFORMATION = "needs_more_information"
    UNABLE_TO_DETERMINE = "unable_to_determine"


class CaseField(BaseModel, Generic[T]):
    status: FieldStatus = FieldStatus.UNKNOWN
    value: T | None = None
    raw_value: str | None = None
    confidence: float | None = None
    source_turn: int | None = None

    def is_usable(self) -> bool:
        return self.status == FieldStatus.KNOWN and self.value is not None


IncomePeriod = Literal[
    "daily",
    "weekly",
    "biweekly",
    "semimonthly",
    "monthly",
    "annual",
]
GrossOrNet = Literal["gross", "net"]
HouseholdOrIndividual = Literal["household", "individual"]


class Contradiction(BaseModel):
    field: str
    previous_value: ScalarValue | None = None
    proposed_value: ScalarValue | None = None
    turn: int
    resolved: bool = False
    note: str | None = None


class Assessment(BaseModel):
    status: AssessmentStatus
    reasons: list[str] = Field(default_factory=list)
    rule_version: str
    source_ids: list[str] = Field(default_factory=list)
    threshold_used: float | None = None
    normalized_gross_monthly: float | None = None
    household_size: int | None = None
    caveats: list[str] = Field(default_factory=list)


class DialogueTurn(BaseModel):
    """Transcript for wording continuity only — not eligibility truth."""

    role: Literal["user", "assistant"]
    text: str


# Screening chats are short; 25 turns is effectively "the whole conversation"
# for this POC while still bounding prompt size / Redis payload / re-injected text.
MAX_RECENT_TURNS = 25

# Fallback if program pack cannot be loaded (tests may override via fresh_case)
OPENING_MESSAGE = (
    "Hi — I can help with a quick eligibility screen. "
    "Can you start by telling me a little about your household and income?"
)


def fresh_case(
    *,
    program_slug: str,
    ruleset_id: str | None = None,
    as_of: str | None = None,
    ruleset_effective_from: str | None = None,
    ruleset_effective_to: str | None = None,
    opening_message: str | None = None,
) -> EligibilityCase:
    """New case with explicit program binding and a friendly opening line."""
    slug = (program_slug or "").strip()
    if not slug:
        raise ValueError("program_slug is required (no default program)")
    as_of_s = as_of or date.today().isoformat()
    as_of_d = date.fromisoformat(as_of_s)
    if ruleset_id and ruleset_effective_from is not None:
        rid = ruleset_id
        eff_from = ruleset_effective_from
        eff_to = ruleset_effective_to
    else:
        rs = resolve_ruleset(slug, as_of_d)
        rid = rs.id
        eff_from = rs.effective_from
        eff_to = rs.effective_to
    try:
        opening = opening_message or get_program(slug).opening_message
    except Exception:
        opening = opening_message or OPENING_MESSAGE

    case = EligibilityCase(
        program_slug=slug,
        ruleset_id=rid,
        as_of=as_of_s,
        ruleset_effective_from=eff_from,
        ruleset_effective_to=eff_to,
    )
    case.append_turn("assistant", opening)
    case.last_question = opening
    return case


class EligibilityCase(BaseModel):
    stage: Stage = Stage.INTRODUCTION
    turn_count: int = 0
    last_question: str | None = None
    last_missing_fields: list[str] = Field(default_factory=list)

    # Program silo (required; pinned at session create — never invent a default)
    program_slug: str = ""
    ruleset_id: str = ""
    as_of: str = ""  # ISO date
    ruleset_effective_from: str | None = None
    ruleset_effective_to: str | None = None  # null = open-ended
    period_notice_given: bool = False

    # Residency
    lives_in_nc: CaseField[bool] = Field(default_factory=CaseField)

    # Household
    household_size: CaseField[int] = Field(default_factory=CaseField)

    # Income
    income_amount: CaseField[float] = Field(default_factory=CaseField)
    income_period: CaseField[IncomePeriod] = Field(default_factory=CaseField)
    gross_or_net: CaseField[GrossOrNet] = Field(default_factory=CaseField)
    household_or_individual: CaseField[HouseholdOrIndividual] = Field(default_factory=CaseField)
    normalized_gross_monthly: CaseField[float] = Field(default_factory=CaseField)

    # Special cases
    is_student: CaseField[bool] = Field(default_factory=CaseField)
    elderly_or_disabled_member: CaseField[bool] = Field(default_factory=CaseField)

    contradictions: list[Contradiction] = Field(default_factory=list)
    assessment: Assessment | None = None

    # Soft flags from safety (non-blocking unless safety handler stops)
    pii_warned: bool = False
    notes: list[str] = Field(default_factory=list)
    # One-shot follow-ups for incomplete income (no invented math)
    asked_for_gross_amount: bool = False
    asked_for_household_total: bool = False

    # Wording-only chat memory (does not drive eligibility)
    recent_turns: list[DialogueTurn] = Field(default_factory=list)
    # Soft disclaimer already woven into an earlier assistant reply
    disclaimer_given: bool = False

    def append_turn(
        self,
        role: Literal["user", "assistant"],
        text: str,
        *,
        max_chars: int | None = None,
    ) -> bool:
        """
        Append a transcript line. Returns True if the text was truncated.

        Callers must PII-redact *user* text before calling. Empty strings are ignored.
        User input over the shared limit is rejected in process_turn (friendly reply)
        and never passed here as a full paste. max_chars is a safety net for retention
        (defaults to Settings / DEFAULT_MAX_MESSAGE_CHARS).
        """
        cleaned = text.strip()
        if not cleaned:
            return False
        limit = max_chars if max_chars is not None else DEFAULT_MAX_MESSAGE_CHARS
        truncated = False
        if len(cleaned) > limit:
            cleaned = cleaned[: limit - 3] + "..."
            truncated = True
        self.recent_turns.append(DialogueTurn(role=role, text=cleaned))
        if len(self.recent_turns) > MAX_RECENT_TURNS:
            self.recent_turns = self.recent_turns[-MAX_RECENT_TURNS:]
        return truncated

    def known_summary(self) -> JsonObject:
        """Compact view of *facts* for LLM prompts (no transcript, no stage labels)."""
        out: JsonObject = {}
        self._put_field(out, "lives_in_nc", self.lives_in_nc)
        self._put_field(out, "household_size", self.household_size)
        self._put_field(out, "income_amount", self.income_amount)
        self._put_field(out, "income_period", self.income_period)
        self._put_field(out, "gross_or_net", self.gross_or_net)
        self._put_field(out, "household_or_individual", self.household_or_individual)
        self._put_field(out, "normalized_gross_monthly", self.normalized_gross_monthly)
        self._put_field(out, "is_student", self.is_student)
        self._put_field(out, "elderly_or_disabled_member", self.elderly_or_disabled_member)

        if self.contradictions:
            open_c: list[JsonValue] = [
                {
                    "field": c.field,
                    "previous_value": c.previous_value,
                    "proposed_value": c.proposed_value,
                    "turn": c.turn,
                    "resolved": c.resolved,
                    "note": c.note,
                }
                for c in self.contradictions
                if not c.resolved
            ]
            out["open_contradictions"] = open_c
        return out

    @staticmethod
    def _put_field(out: JsonObject, name: str, case_field: CaseField[T]) -> None:
        if case_field.status == FieldStatus.UNKNOWN:
            return
        value = case_field.value
        json_value: JsonValue
        if value is None or isinstance(value, bool | int | float | str):
            json_value = value
        else:
            json_value = str(value)
        out[name] = {
            "status": case_field.status.value,
            "value": json_value,
            "raw": case_field.raw_value,
        }
