"""
Ruleset type + default active ruleset for the default program pack.

DUAL COPY (nc-fns): programs/nc-fns/rules/*.yaml ↔ programs/nc-fns/knowledge/nc-fns-income-limits.md
See AGENTS.md.
"""

from __future__ import annotations

from datetime import date

from src.programs.models import Ruleset
from src.programs.registry import default_program_slug, resolve_ruleset

# Re-export for existing imports
__all__ = ["RULESET", "Ruleset", "active_ruleset"]


def active_ruleset(
    *,
    program_slug: str | None = None,
    as_of: date | None = None,
) -> Ruleset:
    slug = program_slug or default_program_slug()
    return resolve_ruleset(slug, as_of)


# Module-level default for tests and call sites that still import RULESET
RULESET: Ruleset = active_ruleset()
