"""Program pack registry — program-agnostic loaders over programs/ on disk."""

from src.programs.registry import (
    ProgramNotAvailableError,
    ProgramNotFoundError,
    catalog_programs,
    get_program,
    list_enabled_slugs,
    resolve_ruleset,
)

__all__ = [
    "ProgramNotAvailableError",
    "ProgramNotFoundError",
    "catalog_programs",
    "get_program",
    "list_enabled_slugs",
    "resolve_ruleset",
]
