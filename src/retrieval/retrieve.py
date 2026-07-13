"""Vector retrieval over Qdrant (RAG only — no keyword path)."""

from __future__ import annotations

import logging

from src.config import get_settings
from src.programs.registry import default_program_slug
from src.retrieval.embeddings import embed_query
from src.retrieval.index import ensure_index, vector_index_ready
from src.retrieval.kb import Citation, enrich_citation
from src.retrieval.qdrant_store import StoredChunk, make_client, search

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    *,
    program_slug: str | None = None,
    source_ids: list[str] | None = None,
    limit: int = 3,
) -> list[Citation]:
    """
    Semantic search over one program silo only (mandatory program_slug pre-filter).

    When source_ids is set (assessment grounding), prefer those sources first
    still within the same program_slug.
    """
    slug = (program_slug or "").strip() or default_program_slug()
    ensure_index()
    if not vector_index_ready():
        logger.debug("Vector index not ready — retrieve returns no citations")
        return []

    settings = get_settings()
    top_k = limit if limit > 0 else settings.retrieval_top_k
    q = query.strip() or "eligibility income household"
    return _vector_retrieve(q, program_slug=slug, source_ids=source_ids, limit=top_k)


def _vector_retrieve(
    query: str,
    *,
    program_slug: str,
    source_ids: list[str] | None,
    limit: int,
) -> list[Citation]:
    settings = get_settings()
    try:
        vector = embed_query(query)
        if not vector:
            return []
        client = make_client(settings.effective_qdrant_url())
    except Exception:
        logger.exception("RAG retrieve setup failed for query=%r", query[:80])
        return []

    hits: list[StoredChunk] = []
    try:
        if source_ids:
            preferred = search(
                client,
                vector,
                program_slug=program_slug,
                limit=limit,
                source_ids=source_ids,
            )
            hits.extend(preferred)
            # Fill remaining only within the same program (never unfiltered)
            if len(hits) < limit:
                rest = search(
                    client,
                    vector,
                    program_slug=program_slug,
                    limit=limit * 2,
                    source_ids=None,
                )
                seen = {h.source_id for h in hits}
                for h in rest:
                    if h.source_id in seen:
                        continue
                    hits.append(h)
                    seen.add(h.source_id)
                    if len(hits) >= limit:
                        break
        else:
            hits = search(
                client,
                vector,
                program_slug=program_slug,
                limit=limit * 2,
                source_ids=None,
            )
    except Exception:
        logger.exception("Qdrant search failed")
        return []

    best: dict[str, StoredChunk] = {}
    ordered_ids: list[str] = []
    for h in hits:
        if not h.source_id:
            continue
        if h.source_id not in best or h.score > best[h.source_id].score:
            if h.source_id not in best:
                ordered_ids.append(h.source_id)
            best[h.source_id] = h

    if source_ids:
        ordered_ids = [sid for sid in source_ids if sid in best] + [
            sid for sid in ordered_ids if sid not in source_ids
        ]

    citations: list[Citation] = []
    for sid in ordered_ids[:limit]:
        h = best[sid]
        snippet = h.chunk_text.strip()
        if len(snippet) > 400:
            snippet = snippet[:397] + "..."
        raw = Citation(
            source_id=h.source_id,
            title=h.title or h.source_id,
            url=h.url,
            snippet=snippet,
            effective_from=h.effective_from,
            effective_to=h.effective_to,
            program_slug=program_slug,
        )
        citations.append(enrich_citation(raw, program_slug=program_slug))
    return citations


def retrieve_supporting_policy(
    assessment_source_ids: list[str],
    *,
    user_query: str = "",
    limit: int = 3,
    program_slug: str | None = None,
) -> list[Citation]:
    return retrieve(
        user_query or "eligibility income household",
        program_slug=program_slug,
        source_ids=assessment_source_ids,
        limit=limit,
    )
