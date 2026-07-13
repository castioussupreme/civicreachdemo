"""Typed requirement modules for declare-driven eligibility."""

from __future__ import annotations

from src.eligibility.modules.base import (
    SOFT_MODULE_TYPES,
    MissingItem,
    ModuleOutcome,
    ModuleResult,
    RequirementModule,
    RequirementSpec,
)
from src.eligibility.modules.elderly import ElderlyDisabledCaveatModule
from src.eligibility.modules.gross_income import GrossIncomeLimitModule
from src.eligibility.modules.household_size import HouseholdSizeModule
from src.eligibility.modules.residency import ResidencyModule
from src.eligibility.modules.student_soft import StudentSoftUnableModule

_MODULES: tuple[RequirementModule, ...] = (
    ResidencyModule(),
    HouseholdSizeModule(),
    GrossIncomeLimitModule(),
    StudentSoftUnableModule(),
    ElderlyDisabledCaveatModule(),
)

MODULE_REGISTRY: dict[str, RequirementModule] = {m.type_id: m for m in _MODULES}


def get_module(type_id: str) -> RequirementModule:
    try:
        return MODULE_REGISTRY[type_id]
    except KeyError as exc:
        raise ValueError(f"Unknown requirement type: {type_id}") from exc


def parse_requirement(raw: object) -> RequirementSpec:
    """Parse one YAML requirement mapping into a validated RequirementSpec."""
    if not isinstance(raw, dict):
        raise ValueError("each requirement must be a mapping with type:")
    type_raw = raw.get("type")
    if not type_raw or not str(type_raw).strip():
        raise ValueError("requirement missing type")
    type_id = str(type_raw).strip()
    module = get_module(type_id)
    params_raw = {str(k): v for k, v in raw.items() if k != "type"}
    params = module.validate(params_raw)
    return RequirementSpec(type=type_id, params=params)


def parse_requirements(raw: object) -> tuple[RequirementSpec, ...]:
    if raw is None:
        raise ValueError("requirements is required (non-empty list)")
    if not isinstance(raw, list) or not raw:
        raise ValueError("requirements must be a non-empty list")
    return tuple(parse_requirement(item) for item in raw)


__all__ = [
    "MODULE_REGISTRY",
    "SOFT_MODULE_TYPES",
    "MissingItem",
    "ModuleOutcome",
    "ModuleResult",
    "RequirementModule",
    "RequirementSpec",
    "get_module",
    "parse_requirement",
    "parse_requirements",
]
