"""Requirement module contracts (declare-driven eligibility)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from src.programs.models import ProgramMeta
from src.state.models import EligibilityCase

if TYPE_CHECKING:
    from src.programs.models import Ruleset


@dataclass(frozen=True)
class RequirementSpec:
    """One declared requirement on a ruleset (type + validated params)."""

    type: str
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MissingItem:
    field_key: str
    question_hint: str


class ModuleOutcome(StrEnum):
    NEED_MORE = "need_more"
    PASS = "pass"
    FAIL = "fail"
    UNABLE = "unable"
    SKIP = "skip"


@dataclass(frozen=True)
class ModuleResult:
    outcome: ModuleOutcome
    reasons: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    threshold_used: float | None = None
    normalized_gross_monthly: float | None = None
    household_size: int | None = None


# Soft modules may still run after a hard FAIL (annotations only).
SOFT_MODULE_TYPES = frozenset({"student_soft_unable", "elderly_disabled_caveat"})


class RequirementModule(Protocol):
    type_id: str

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        """Normalize/validate params; raise ValueError on bad config."""
        ...

    def missing(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
    ) -> list[MissingItem]: ...

    def assess(
        self,
        case: EligibilityCase,
        spec: RequirementSpec,
        *,
        program: ProgramMeta,
        ruleset: Ruleset | None = None,
        ruleset_source_id: str = "",
        supporting_source_ids: tuple[str, ...] = (),
    ) -> ModuleResult: ...


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(str(value))


def reject_unknown_keys(
    params: Mapping[str, object], allowed: frozenset[str], type_id: str
) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"{type_id}: unknown param keys: {sorted(unknown)}")
