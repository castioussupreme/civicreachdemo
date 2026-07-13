"""
Ruleset type re-export + explicit pack loader (no default program).

DUAL COPY (nc-fns example): programs/nc-fns/rules/*.yaml ↔ knowledge income tables.
See AGENTS.md.
"""

from __future__ import annotations

from datetime import date

from src.programs.models import Ruleset
from src.programs.registry import resolve_ruleset

__all__ = ["Ruleset", "load_ruleset"]


def load_ruleset(program_slug: str, as_of: date | None = None) -> Ruleset:
    """Load the active ruleset for an explicit program slug (required)."""
    slug = (program_slug or "").strip()
    if not slug:
        raise ValueError("program_slug is required (no default program)")
    return resolve_ruleset(slug, as_of)
