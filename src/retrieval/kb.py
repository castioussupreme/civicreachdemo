"""Knowledge corpus loaders and citation types (shared by RAG)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.config import KNOWLEDGE_DIR
from src.programs.registry import default_program_slug, get_program


@dataclass(frozen=True)
class SourceDoc:
    id: str
    title: str
    file: str
    url: str | None
    publisher: str | None
    effective_from: str | None
    effective_to: str | None
    notes: str | None
    text: str
    program_slug: str = ""


@dataclass(frozen=True)
class Citation:
    source_id: str
    title: str
    url: str | None
    snippet: str
    effective_from: str | None = None
    effective_to: str | None = None
    program_slug: str = ""


@lru_cache
def load_corpus(program_slug: str = "") -> tuple[SourceDoc, ...]:
    slug = program_slug or default_program_slug()
    try:
        knowledge_dir = get_program(slug).knowledge_dir
    except Exception:
        knowledge_dir = KNOWLEDGE_DIR
    return _load_corpus_dir(knowledge_dir, slug)


def _load_corpus_dir(knowledge_dir: Path, program_slug: str) -> tuple[SourceDoc, ...]:
    manifest_path = knowledge_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs: list[SourceDoc] = []
    for s in data["sources"]:
        path = knowledge_dir / s["file"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        docs.append(
            SourceDoc(
                id=s["id"],
                title=s["title"],
                file=s["file"],
                url=s.get("url"),
                publisher=s.get("publisher"),
                effective_from=s.get("effective_from"),
                effective_to=s.get("effective_to"),
                notes=s.get("notes"),
                text=text,
                program_slug=program_slug,
            )
        )
    return tuple(docs)


def get_by_id(source_id: str, *, program_slug: str = "") -> SourceDoc | None:
    for d in load_corpus(program_slug):
        if d.id == source_id:
            return d
    return None


# Internal / agent-owned ids — never show as public citations
_INTERNAL_SOURCE_IDS = frozenset({"agent-disclaimer"})


def is_public_source_id(source_id: str) -> bool:
    return bool(source_id) and source_id not in _INTERNAL_SOURCE_IDS


def enrich_citation(citation: Citation, *, program_slug: str = "") -> Citation:
    """Fill title/url from the corpus when the vector hit is incomplete."""
    slug = program_slug or citation.program_slug
    doc = get_by_id(citation.source_id, program_slug=slug)
    if doc is None:
        return citation
    return Citation(
        source_id=citation.source_id,
        title=(
            citation.title if citation.title and citation.title != citation.source_id else doc.title
        )
        or doc.title,
        url=citation.url or doc.url,
        snippet=citation.snippet,
        effective_from=citation.effective_from or doc.effective_from,
        effective_to=citation.effective_to or doc.effective_to,
        program_slug=slug or doc.program_slug,
    )


def public_citations_from_ids(
    source_ids: list[str],
    *,
    limit: int = 4,
    program_slug: str = "",
) -> list[Citation]:
    """Resolve assessment source_ids to human-facing citations (title + URL)."""
    out: list[Citation] = []
    seen: set[str] = set()
    for sid in source_ids:
        if not is_public_source_id(sid) or sid in seen:
            continue
        seen.add(sid)
        doc = get_by_id(sid, program_slug=program_slug)
        if doc is None or not (doc.title or doc.url):
            continue
        out.append(
            Citation(
                source_id=doc.id,
                title=doc.title,
                url=doc.url,
                snippet=(doc.notes or doc.title)[:280],
                effective_from=doc.effective_from,
                effective_to=doc.effective_to,
                program_slug=program_slug or doc.program_slug,
            )
        )
        if len(out) >= limit:
            break
    return out


def public_citation_dicts(
    citations: list[Citation] | None = None,
    *,
    source_ids: list[str] | None = None,
    limit: int = 4,
    program_slug: str = "",
) -> list[dict[str, str]]:
    """Client-safe citation list: real titles and URLs only (no source ids)."""
    merged: list[Citation] = []
    seen: set[str] = set()

    for c in citations or []:
        if not is_public_source_id(c.source_id) or c.source_id in seen:
            continue
        seen.add(c.source_id)
        merged.append(enrich_citation(c, program_slug=program_slug))

    if source_ids:
        for c in public_citations_from_ids(source_ids, limit=limit, program_slug=program_slug):
            if c.source_id in seen:
                continue
            seen.add(c.source_id)
            merged.append(c)

    out: list[dict[str, str]] = []
    for c in merged:
        title = (c.title or "").strip()
        if not title or title == c.source_id:
            doc = get_by_id(c.source_id, program_slug=program_slug or c.program_slug)
            title = (doc.title if doc else "") or ""
        if not title:
            continue
        item: dict[str, str] = {"title": title}
        url = c.url
        if not url:
            doc = get_by_id(c.source_id, program_slug=program_slug or c.program_slug)
            url = doc.url if doc else None
        if url:
            item["url"] = url
        doc = get_by_id(c.source_id, program_slug=program_slug or c.program_slug)
        if doc and doc.publisher:
            item["publisher"] = doc.publisher
        out.append(item)
        if len(out) >= limit:
            break
    return out


def format_citations(citations: list[Citation]) -> str:
    """Human-facing source list: title + URL (no internal source ids)."""
    public = [enrich_citation(c) for c in citations if is_public_source_id(c.source_id)]
    usable: list[Citation] = []
    for c in public:
        title = (c.title or "").strip()
        if (title and title != c.source_id) or c.url:
            usable.append(c)
    if not usable:
        return ""
    lines = ["Public sources"]
    for c in usable:
        title = (c.title or "").strip()
        if not title or title == c.source_id:
            title = "Public source"
        if c.url:
            lines.append(f"  • {title}")
            lines.append(f"    {c.url}")
        else:
            lines.append(f"  • {title}")
    return "\n".join(lines)


def retrieve(
    query: str,
    *,
    source_ids: list[str] | None = None,
    limit: int = 3,
    program_slug: str = "",
    as_of: str | None = None,
) -> list[Citation]:
    from src.retrieval.retrieve import retrieve as _vector_retrieve  # noqa: PLC0415

    return _vector_retrieve(
        query,
        source_ids=source_ids,
        limit=limit,
        program_slug=program_slug,
        as_of=as_of,
    )


def retrieve_supporting_policy(
    assessment_source_ids: list[str],
    *,
    user_query: str = "",
    limit: int = 3,
    program_slug: str = "",
    as_of: str | None = None,
) -> list[Citation]:
    from src.retrieval.retrieve import (  # noqa: PLC0415
        retrieve_supporting_policy as _vector_support,
    )

    return _vector_support(
        assessment_source_ids,
        user_query=user_query,
        limit=limit,
        program_slug=program_slug,
        as_of=as_of,
    )


def clear_corpus_cache() -> None:
    load_corpus.cache_clear()
