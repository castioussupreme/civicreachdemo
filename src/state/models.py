from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from src.json_types import JsonObject, JsonValue

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


IncomePeriod = Literal["weekly", "biweekly", "monthly", "annual"]
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


class EligibilityCase(BaseModel):
    stage: Stage = Stage.INTRODUCTION
    turn_count: int = 0
    last_question: str | None = None
    last_missing_fields: list[str] = Field(default_factory=list)

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

    def known_summary(self) -> JsonObject:
        """Compact view for LLM prompts and debugging."""
        out: JsonObject = {"stage": self.stage.value}
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
        if self.assessment:
            a = self.assessment
            out["assessment"] = {
                "status": a.status.value,
                "reasons": list(a.reasons),
                "rule_version": a.rule_version,
                "source_ids": list(a.source_ids),
                "threshold_used": a.threshold_used,
                "normalized_gross_monthly": a.normalized_gross_monthly,
                "household_size": a.household_size,
                "caveats": list(a.caveats),
            }
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
