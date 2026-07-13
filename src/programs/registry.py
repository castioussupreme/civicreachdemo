"""Load programs/ registry, metadata, and ruleset versions."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from src.programs.models import CatalogEntry, ProgramMeta, Ruleset

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "programs"
REGISTRY_PATH = PROGRAMS_DIR / "registry.yaml"


class ProgramNotFoundError(LookupError):
    pass


class ProgramNotAvailableError(LookupError):
    """Program exists but has no ruleset covering as_of (or program-level inactive)."""


def list_enabled_slugs() -> list[str]:
    data = _load_yaml(REGISTRY_PATH)
    raw = data.get("programs") or []
    if not isinstance(raw, list):
        return []
    return [str(s) for s in raw]


def get_program(slug: str) -> ProgramMeta:
    slug = slug.strip()
    if slug not in list_enabled_slugs():
        raise ProgramNotFoundError(f"Unknown or disabled program: {slug}")
    root = PROGRAMS_DIR / slug
    meta_path = root / "program.yaml"
    if not meta_path.is_file():
        raise ProgramNotFoundError(f"Missing program.yaml for {slug}")
    data = _load_yaml(meta_path)
    aliases = data.get("search_aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    opening = str(data.get("opening_message") or "").strip()
    if not opening:
        opening = f"Hi — I can help screen for {data.get('display_name') or slug}."
    return ProgramMeta(
        slug=str(data.get("slug") or slug),
        display_name=str(data.get("display_name") or slug),
        search_aliases=tuple(str(a) for a in aliases),
        program_effective_from=_opt_str(data.get("program_effective_from")),
        program_effective_to=_opt_str(data.get("program_effective_to")),
        opening_message=opening,
        root=root,
    )


def load_all_rulesets(slug: str) -> list[Ruleset]:
    prog = get_program(slug)
    rules_dir = prog.rules_dir
    if not rules_dir.is_dir():
        return []
    out: list[Ruleset] = []
    for path in sorted(rules_dir.glob("*.yaml")):
        out.append(_ruleset_from_yaml(path, program_slug=slug))
    return out


def resolve_ruleset(slug: str, as_of: date | None = None) -> Ruleset:
    """Pick the ruleset covering as_of (latest effective_from wins on overlap)."""
    when = as_of or date.today()
    prog = get_program(slug)
    if not prog.program_active(when):
        raise ProgramNotAvailableError(f"Program {slug} is not active for as_of={when.isoformat()}")
    candidates = [r for r in load_all_rulesets(slug) if r.covers(when)]
    if not candidates:
        raise ProgramNotAvailableError(
            f"No ruleset for program {slug} covers as_of={when.isoformat()}"
        )
    candidates.sort(key=lambda r: r.effective_from_date(), reverse=True)
    return candidates[0]


def get_ruleset_by_id(slug: str, ruleset_id: str) -> Ruleset:
    for r in load_all_rulesets(slug):
        if r.id == ruleset_id:
            return r
    raise ProgramNotFoundError(f"Ruleset {ruleset_id} not found for program {slug}")


def catalog_programs(
    *,
    q: str = "",
    as_of: date | None = None,
    limit: int = 20,
) -> list[CatalogEntry]:
    """Active programs for as_of, optional substring filter, capped list."""
    when = as_of or date.today()
    limit = max(1, min(limit, 100))
    entries: list[CatalogEntry] = []
    for slug in list_enabled_slugs():
        try:
            prog = get_program(slug)
        except ProgramNotFoundError:
            continue
        if not prog.matches_query(q):
            continue
        try:
            ruleset = resolve_ruleset(slug, when)
        except (ProgramNotFoundError, ProgramNotAvailableError):
            continue
        entries.append(
            CatalogEntry(
                slug=prog.slug,
                display_name=prog.display_name,
                ruleset_id=ruleset.id,
                effective_from=ruleset.effective_from,
                effective_to=ruleset.effective_to,
                search_aliases=prog.search_aliases,
            )
        )
    entries.sort(key=lambda e: e.display_name.lower())
    return entries[:limit]


def default_program_slug() -> str:
    slugs = list_enabled_slugs()
    if not slugs:
        raise ProgramNotFoundError("No programs registered in programs/registry.yaml")
    return slugs[0]


@lru_cache
def _load_yaml_cached(path_str: str, mtime_ns: int) -> dict[str, object]:
    # mtime_ns is part of the cache key so file edits bust the cache
    _ = mtime_ns
    path = Path(path_str)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items()}


def _load_yaml(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    st = path.stat()
    return dict(_load_yaml_cached(str(path.resolve()), st.st_mtime_ns))


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _ruleset_from_yaml(path: Path, *, program_slug: str) -> Ruleset:
    data = _load_yaml(path)
    table_raw = data.get("max_gross_monthly_by_size") or {}
    table: dict[int, float] = {}
    if isinstance(table_raw, dict):
        for k, v in table_raw.items():
            table[int(str(k))] = float(str(v))
    eff_to = data.get("effective_to")
    effective_to: str | None
    if eff_to is None or eff_to == "" or str(eff_to).lower() == "null":
        effective_to = None
    else:
        effective_to = str(eff_to)
    inc_raw = data.get("additional_member_increment")
    try:
        increment = float(str(inc_raw if inc_raw is not None else 0))
    except ValueError:
        increment = 0.0
    return Ruleset(
        id=str(data["id"]),
        effective_from=str(data["effective_from"]),
        effective_to=effective_to,
        source_id=str(data.get("source_id") or ""),
        description=str(data.get("description") or ""),
        max_gross_monthly_by_size=table,
        additional_member_increment=increment,
        program_slug=program_slug,
    )


def clear_registry_cache() -> None:
    _load_yaml_cached.cache_clear()
