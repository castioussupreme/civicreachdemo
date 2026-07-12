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


def format_citations(citations: list[Citation]) -> str:
    if not citations:
        return ""
    lines = ["Sources:"]
    for c in citations:
        eff = ""
        if c.effective_from:
            eff = f" (effective {c.effective_from}"
            if c.effective_to:
                eff += f" to {c.effective_to}"
            eff += ")"
        url = f" — {c.url}" if c.url else ""
        lines.append(f"- [{c.source_id}] {c.title}{eff}{url}")
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
