from __future__ import annotations

import json
import re
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


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def retrieve(
    query: str,
    *,
    source_ids: list[str] | None = None,
    limit: int = 3,
) -> list[Citation]:
    """
    Simple keyword retrieval over curated docs.
    If source_ids provided, prefer those (assessment grounding).
    """
    docs = list(load_corpus())
    if source_ids:
        preferred = [d for d in docs if d.id in source_ids]
        # Keep preferred order by source_ids
        preferred.sort(key=lambda d: source_ids.index(d.id) if d.id in source_ids else 99)
        others = [d for d in docs if d.id not in source_ids]
        ordered = preferred + others
    else:
        ordered = docs

    q_tokens = _tokenize(query)
    scored: list[tuple[float, SourceDoc]] = []
    for d in ordered:
        overlap = float(len(q_tokens & _tokenize(d.text + " " + d.title)))
        score = 100.0 + overlap if source_ids and d.id in source_ids else overlap
        if score > 0 or (source_ids and d.id in source_ids):
            scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    citations: list[Citation] = []
    for _, d in scored[:limit]:
        snippet = d.text.strip().split("\n\n")[0][:400]
        citations.append(
            Citation(
                source_id=d.id,
                title=d.title,
                url=d.url,
                snippet=snippet,
                effective_from=d.effective_from,
                effective_to=d.effective_to,
            )
        )
    return citations


def retrieve_supporting_policy(
    assessment_source_ids: list[str],
    *,
    user_query: str = "",
    limit: int = 3,
) -> list[Citation]:
    return retrieve(
        user_query or "eligibility income household", source_ids=assessment_source_ids, limit=limit
    )


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
