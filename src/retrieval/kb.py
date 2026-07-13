"""Knowledge corpus loaders and citation types (shared by RAG)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from src.config import KNOWLEDGE_DIR


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


@dataclass(frozen=True)
class Citation:
    source_id: str
    title: str
    url: str | None
    snippet: str
    effective_from: str | None = None
    effective_to: str | None = None


@lru_cache
def load_corpus() -> tuple[SourceDoc, ...]:
    manifest_path = KNOWLEDGE_DIR / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs: list[SourceDoc] = []
    for s in data["sources"]:
        path = KNOWLEDGE_DIR / s["file"]
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
            )
        )
    return tuple(docs)


def get_by_id(source_id: str) -> SourceDoc | None:
    for d in load_corpus():
        if d.id == source_id:
            return d
    return None


# Internal / agent-owned ids — never show as public citations
_INTERNAL_SOURCE_IDS = frozenset({"agent-disclaimer"})


def is_public_source_id(source_id: str) -> bool:
    return bool(source_id) and source_id not in _INTERNAL_SOURCE_IDS


def enrich_citation(citation: Citation) -> Citation:
    """Fill title/url from the corpus when the vector hit is incomplete."""
    doc = get_by_id(citation.source_id)
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
    )


def public_citations_from_ids(
    source_ids: list[str],
    *,
    limit: int = 4,
) -> list[Citation]:
    """Resolve assessment source_ids to human-facing citations (title + URL)."""
    out: list[Citation] = []
    seen: set[str] = set()
    for sid in source_ids:
        if not is_public_source_id(sid) or sid in seen:
            continue
        seen.add(sid)
        doc = get_by_id(sid)
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
) -> list[dict[str, str]]:
    """
    Client-safe citation list: real titles and URLs only (no source ids).

    Prefer turn citations; fill gaps from assessment source_ids via the corpus.
    """
    merged: list[Citation] = []
    seen: set[str] = set()

    for c in citations or []:
        if not is_public_source_id(c.source_id) or c.source_id in seen:
            continue
        seen.add(c.source_id)
        merged.append(enrich_citation(c))

    if source_ids:
        for c in public_citations_from_ids(source_ids, limit=limit):
            if c.source_id in seen:
                continue
            seen.add(c.source_id)
            merged.append(c)

    out: list[dict[str, str]] = []
    for c in merged:
        title = (c.title or "").strip()
        if not title or title == c.source_id:
            doc = get_by_id(c.source_id)
            title = (doc.title if doc else "") or ""
        if not title:
            continue
        item: dict[str, str] = {"title": title}
        url = c.url
        if not url:
            doc = get_by_id(c.source_id)
            url = doc.url if doc else None
        if url:
            item["url"] = url
        doc = get_by_id(c.source_id)
        if doc and doc.publisher:
            item["publisher"] = doc.publisher
        out.append(item)
        if len(out) >= limit:
            break
    return out


def format_citations(citations: list[Citation]) -> str:
    """Human-facing source list: title + URL (no internal source ids)."""
    public = [enrich_citation(c) for c in citations if is_public_source_id(c.source_id)]
    # Drop entries with neither a real title nor a URL
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


# Public retrieve API (vector RAG) — re-exported for stable imports.
# Lazy imports avoid circular import with retrieve.py → kb.Citation.
def retrieve(
    query: str,
    *,
    source_ids: list[str] | None = None,
    limit: int = 3,
) -> list[Citation]:
    from src.retrieval.retrieve import retrieve as _vector_retrieve  # noqa: PLC0415

    return _vector_retrieve(query, source_ids=source_ids, limit=limit)


def retrieve_supporting_policy(
    assessment_source_ids: list[str],
    *,
    user_query: str = "",
    limit: int = 3,
) -> list[Citation]:
    from src.retrieval.retrieve import (  # noqa: PLC0415
        retrieve_supporting_policy as _vector_support,
    )

    return _vector_support(assessment_source_ids, user_query=user_query, limit=limit)
