"""Incremental knowledge index sync into Qdrant (all program packs)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from src.config import get_settings
from src.openai_errors import OpenAIServiceError, log_service_error
from src.programs.registry import get_program, list_enabled_slugs
from src.retrieval.chunking import chunk_markdown
from src.retrieval.embeddings import embed_texts
from src.retrieval.kb import SourceDoc, clear_corpus_cache, load_corpus
from src.retrieval.qdrant_store import (
    content_hash,
    delete_source,
    ensure_collection,
    list_indexed_source_ids,
    make_client,
    source_hash_in_store,
    upsert_chunks,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class _IndexState:
    """Process-wide index status."""

    synced: bool = False
    degraded: bool = False
    last_error: str | None = None


@dataclass(frozen=True)
class SyncResult:
    skipped: int
    reembedded: int
    orphans_deleted: int
    chunks_upserted: int


def vector_index_ready() -> bool:
    return _IndexState.synced and not _IndexState.degraded


def index_degraded_message() -> str | None:
    if _IndexState.degraded:
        return _IndexState.last_error or "index sync failed"
    return None


def sync_knowledge_index(*, force: bool = False) -> SyncResult:
    """
    Ensure Qdrant reflects all enabled program knowledge packs.

    Only re-embeds documents whose content hash changed.
    Points are tagged with program_slug for pre-filter isolation.
    """
    settings = get_settings()
    client = make_client(settings.effective_qdrant_url())
    ensure_collection(client)
    clear_corpus_cache()

    skipped = 0
    reembedded = 0
    chunks_upserted = 0
    orphans_deleted = 0

    for slug in list_enabled_slugs():
        try:
            get_program(slug)
        except Exception:
            logger.warning("Skipping index for missing pack %s", slug)
            continue
        docs = load_corpus(slug)
        manifest_ids = {d.id for d in docs}
        to_embed: list[tuple[SourceDoc, str]] = []
        for doc in docs:
            digest = content_hash(doc.id, doc.text)
            if not force and source_hash_in_store(client, doc.id, digest, program_slug=slug):
                skipped += 1
                continue
            to_embed.append((doc, digest))

        if to_embed:
            logger.info(
                "Embedding %s source(s) for program=%s: %s",
                len(to_embed),
                slug,
                ", ".join(d.id for d, _ in to_embed),
            )

        for doc, digest in to_embed:
            parts = chunk_markdown(doc.text)
            if not parts:
                logger.warning("No chunks for source_id=%s; skipping", doc.id)
                skipped += 1
                continue
            texts = [c.text for c in parts]
            vectors = embed_texts(texts)
            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"Embedding count mismatch for {doc.id}: {len(vectors)} vs {len(texts)}"
                )
            delete_source(client, doc.id, program_slug=slug)
            upsert_chunks(
                client,
                program_slug=slug,
                source_id=doc.id,
                title=doc.title,
                url=doc.url,
                file_name=doc.file,
                content_hash_value=digest,
                effective_from=doc.effective_from,
                effective_to=doc.effective_to,
                chunks=[(c.index, c.text, vectors[i]) for i, c in enumerate(parts)],
            )
            reembedded += 1
            chunks_upserted += len(parts)
            logger.info(
                "Re-indexed program=%s source_id=%s chunks=%s",
                slug,
                doc.id,
                len(parts),
            )

        indexed = list_indexed_source_ids(client, program_slug=slug)
        orphans = indexed - manifest_ids
        for orphan_id in orphans:
            delete_source(client, orphan_id, program_slug=slug)
            orphans_deleted += 1
            logger.info("Deleted orphan program=%s source_id=%s", slug, orphan_id)

    result = SyncResult(
        skipped=skipped,
        reembedded=reembedded,
        orphans_deleted=orphans_deleted,
        chunks_upserted=chunks_upserted,
    )
    logger.info(
        "Knowledge index sync complete: skipped=%s reembedded=%s orphans=%s chunks=%s",
        result.skipped,
        result.reembedded,
        result.orphans_deleted,
        result.chunks_upserted,
    )
    return result


def ensure_index() -> SyncResult | None:
    with _lock:
        if _IndexState.synced:
            return None
        try:
            result = sync_knowledge_index()
            _IndexState.synced = True
            _IndexState.degraded = False
            _IndexState.last_error = None
            return result
        except Exception as exc:
            _IndexState.degraded = True
            _IndexState.synced = False
            _IndexState.last_error = str(exc)
            if isinstance(exc, OpenAIServiceError):
                log_service_error(exc, where="knowledge index sync")
            else:
                logger.exception("Knowledge index sync failed — refusing to start")
            raise


def reset_index_flag() -> None:
    with _lock:
        _IndexState.synced = False
        _IndexState.degraded = False
        _IndexState.last_error = None
