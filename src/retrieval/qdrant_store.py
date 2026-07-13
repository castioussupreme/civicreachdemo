"""Qdrant client helpers — one collection, pre-filter by program_slug."""

from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from src.retrieval.embeddings import EMBEDDING_DIM

logger = logging.getLogger(__name__)

# Shared multi-program collection (logical shard via program_slug payload)
COLLECTION = "kb_programs"


@dataclass(frozen=True)
class StoredChunk:
    source_id: str
    title: str
    url: str | None
    chunk_text: str
    content_hash: str
    chunk_index: int
    score: float
    program_slug: str = ""
    effective_from: str | None = None
    effective_to: str | None = None


def make_client(url: str) -> QdrantClient:
    # check_compatibility=False: Compose image pin may lag client by a patch/minor.
    return QdrantClient(url=url, prefer_grpc=False, check_compatibility=False)


def ensure_collection(client: QdrantClient, *, vector_size: int = EMBEDDING_DIM) -> None:
    names = {c.name for c in client.get_collections().collections}
    if COLLECTION in names:
        try:
            info = client.get_collection(COLLECTION)
            existing = info.config.params.vectors
            size: int | None = None
            if isinstance(existing, qm.VectorParams):
                size = int(existing.size)
            elif isinstance(existing, dict) and "" in existing:
                params = existing[""]
                if isinstance(params, qm.VectorParams):
                    size = int(params.size)
            if size is not None and size != vector_size:
                logger.warning(
                    "Qdrant collection %s has dim %s, expected %s — recreating",
                    COLLECTION,
                    size,
                    vector_size,
                )
                client.delete_collection(COLLECTION)
            else:
                _ensure_payload_indexes(client)
                return
        except Exception:
            logger.exception("Could not inspect collection %s; recreating", COLLECTION)
            with suppress(Exception):
                client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
    )
    _ensure_payload_indexes(client)


def _ensure_payload_indexes(client: QdrantClient) -> None:
    for field in ("source_id", "program_slug"):
        with suppress(Exception):
            client.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )


def content_hash(source_id: str, text: str) -> str:
    payload = f"{source_id}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def source_hash_in_store(
    client: QdrantClient,
    source_id: str,
    expected_hash: str,
    *,
    program_slug: str,
) -> bool:
    """True if any point for source_id already has this content_hash (doc unchanged)."""
    points, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=qm.Filter(
            must=[
                qm.FieldCondition(key="program_slug", match=qm.MatchValue(value=program_slug)),
                qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id)),
                qm.FieldCondition(key="content_hash", match=qm.MatchValue(value=expected_hash)),
            ]
        ),
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    return len(points) > 0


def delete_source(client: QdrantClient, source_id: str, *, program_slug: str) -> None:
    client.delete(
        collection_name=COLLECTION,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(key="program_slug", match=qm.MatchValue(value=program_slug)),
                    qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id)),
                ]
            )
        ),
    )


def list_indexed_source_ids(client: QdrantClient, *, program_slug: str) -> set[str]:
    ids: set[str] = set()
    next_offset: object | None = None
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=qm.Filter(
                must=[
                    qm.FieldCondition(key="program_slug", match=qm.MatchValue(value=program_slug))
                ]
            ),
            limit=100,
            offset=next_offset,
            with_payload=["source_id"],
            with_vectors=False,
        )
        for p in points:
            if p.payload and "source_id" in p.payload:
                ids.add(str(p.payload["source_id"]))
        if next_offset is None:
            break
    return ids


def upsert_chunks(
    client: QdrantClient,
    *,
    program_slug: str,
    source_id: str,
    title: str,
    url: str | None,
    file_name: str,
    content_hash_value: str,
    effective_from: str | None,
    effective_to: str | None,
    chunks: list[tuple[int, str, list[float]]],
) -> None:
    """chunks: list of (chunk_index, text, vector)."""
    if not program_slug:
        raise ValueError("program_slug is required for upsert_chunks")
    points: list[qm.PointStruct] = []
    for chunk_index, text, vector in chunks:
        point_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{program_slug}:{source_id}:{chunk_index}:{content_hash_value}",
            )
        )
        points.append(
            qm.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "program_slug": program_slug,
                    "source_id": source_id,
                    "title": title,
                    "url": url,
                    "file": file_name,
                    "chunk_index": chunk_index,
                    "chunk_text": text,
                    "content_hash": content_hash_value,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                },
            )
        )
    if points:
        client.upsert(collection_name=COLLECTION, points=points)


def doc_covers_as_of(
    *,
    effective_from: str | None,
    effective_to: str | None,
    as_of: str,
) -> bool:
    """
    True if a knowledge doc is valid on as_of (ISO YYYY-MM-DD).

    null effective_from / effective_to = open on that side (timeless or open-ended).
    """
    if effective_from and as_of < effective_from:
        return False
    return not (effective_to and as_of > effective_to)


def search(
    client: QdrantClient,
    vector: list[float],
    *,
    program_slug: str,
    limit: int = 3,
    source_ids: list[str] | None = None,
    as_of: str | None = None,
) -> list[StoredChunk]:
    """
    Vector search with mandatory program_slug pre-filter (not post-filter).

    Never searches across programs. Optional as_of drops docs outside their
    effective window (within the program silo; over-fetch then date-filter).
    """
    if not program_slug:
        raise ValueError("program_slug is required for search (pre-filter isolation)")
    must: list[qm.Condition] = [
        qm.FieldCondition(key="program_slug", match=qm.MatchValue(value=program_slug)),
    ]
    if source_ids:
        must.append(
            qm.FieldCondition(
                key="source_id",
                match=qm.MatchAny(any=source_ids),
            )
        )
    query_filter = qm.Filter(must=must)
    # Over-fetch when date-filtering so top-k after as_of still has room
    fetch_limit = limit * 4 if as_of else limit
    result = client.query_points(
        collection_name=COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=fetch_limit,
        with_payload=True,
    )
    out: list[StoredChunk] = []
    for h in result.points:
        payload = h.payload or {}
        eff_from = (
            payload.get("effective_from")
            if isinstance(payload.get("effective_from"), str)
            else None
        )
        eff_to = (
            payload.get("effective_to") if isinstance(payload.get("effective_to"), str) else None
        )
        if as_of and not doc_covers_as_of(
            effective_from=eff_from, effective_to=eff_to, as_of=as_of
        ):
            continue
        out.append(
            StoredChunk(
                source_id=str(payload.get("source_id", "")),
                title=str(payload.get("title", "")),
                url=payload.get("url") if isinstance(payload.get("url"), str) else None,
                chunk_text=str(payload.get("chunk_text", "")),
                content_hash=str(payload.get("content_hash", "")),
                chunk_index=int(payload.get("chunk_index") or 0),
                score=float(h.score or 0.0),
                program_slug=str(payload.get("program_slug") or program_slug),
                effective_from=eff_from,
                effective_to=eff_to,
            )
        )
        if len(out) >= limit:
            break
    return out
