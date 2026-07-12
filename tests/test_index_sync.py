"""Incremental index sync (Qdrant + embeddings mocked)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.retrieval.chunking import chunk_markdown
from src.retrieval.index import reset_index_flag, sync_knowledge_index
from src.retrieval.kb import SourceDoc


def _doc(source_id: str = "nc-fns-overview", text: str = "Hello world policy text.") -> SourceDoc:
    return SourceDoc(
        id=source_id,
        title="Overview",
        file=f"{source_id}.md",
        url=None,
        publisher=None,
        effective_from=None,
        effective_to=None,
        notes=None,
        text=text,
    )


@pytest.fixture(autouse=True)
def _reset_flag() -> None:
    reset_index_flag()
    yield
    reset_index_flag()


def test_sync_skips_unchanged_hash() -> None:
    client = MagicMock()
    doc = _doc()
    with (
        patch("src.retrieval.index.get_settings") as gs,
        patch("src.retrieval.index.make_client", return_value=client),
        patch("src.retrieval.index.ensure_collection"),
        patch("src.retrieval.index.load_corpus", return_value=(doc,)),
        patch("src.retrieval.index.source_hash_in_store", return_value=True),
        patch("src.retrieval.index.embed_texts") as embed,
        patch("src.retrieval.index.list_indexed_source_ids", return_value={doc.id}),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.skipped == 1
    assert result.reembedded == 0
    embed.assert_not_called()


def test_sync_reembeds_when_hash_missing() -> None:
    client = MagicMock()
    doc = _doc(text="## Limits\n\nGross income table for household size.")
    fake_vec = [0.1] * 8
    n = len(chunk_markdown(doc.text))

    def _embed(texts: list[str]) -> list[list[float]]:
        return [fake_vec for _ in texts]

    with (
        patch("src.retrieval.index.get_settings") as gs,
        patch("src.retrieval.index.make_client", return_value=client),
        patch("src.retrieval.index.ensure_collection"),
        patch("src.retrieval.index.load_corpus", return_value=(doc,)),
        patch("src.retrieval.index.source_hash_in_store", return_value=False),
        patch("src.retrieval.index.embed_texts", side_effect=_embed) as embed,
        patch("src.retrieval.index.delete_source") as delete,
        patch("src.retrieval.index.upsert_chunks") as upsert,
        patch("src.retrieval.index.list_indexed_source_ids", return_value={doc.id}),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.reembedded == 1
    assert result.skipped == 0
    assert result.chunks_upserted == n
    delete.assert_called_once_with(client, doc.id)
    upsert.assert_called_once()
    embed.assert_called_once()


def test_sync_deletes_orphans() -> None:
    client = MagicMock()
    doc = _doc()
    with (
        patch("src.retrieval.index.get_settings") as gs,
        patch("src.retrieval.index.make_client", return_value=client),
        patch("src.retrieval.index.ensure_collection"),
        patch("src.retrieval.index.load_corpus", return_value=(doc,)),
        patch("src.retrieval.index.source_hash_in_store", return_value=True),
        patch("src.retrieval.index.list_indexed_source_ids", return_value={doc.id, "gone-source"}),
        patch("src.retrieval.index.delete_source") as delete,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.orphans_deleted == 1
    delete.assert_called_with(client, "gone-source")
