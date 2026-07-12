"""Knowledge corpus + vector retrieve (Qdrant/embeddings mocked)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.retrieval.kb import (
    Citation,
    format_citations,
    get_by_id,
    load_corpus,
    retrieve,
    retrieve_supporting_policy,
)
from src.retrieval.qdrant_store import StoredChunk


def test_corpus_loads() -> None:
    docs = load_corpus()
    ids = {d.id for d in docs}
    assert "nc-fns-income-limits" in ids
    assert "agent-disclaimer" in ids
    assert all(d.text.strip() for d in docs)


def test_get_by_id() -> None:
    doc = get_by_id("nc-fns-income-limits")
    assert doc is not None
    assert "income" in doc.title.lower() or "limit" in doc.text.lower()
    assert get_by_id("does-not-exist") is None


def _chunk(
    source_id: str,
    *,
    text: str = "snippet body",
    score: float = 0.9,
    title: str = "Title",
) -> StoredChunk:
    return StoredChunk(
        source_id=source_id,
        title=title,
        url="https://example.com",
        chunk_text=text,
        content_hash="abc",
        chunk_index=0,
        score=score,
        effective_from="2025-10-01",
        effective_to=None,
    )


def test_retrieve_maps_hits_to_citations() -> None:
    hits = [
        _chunk("nc-fns-income-limits", text="Gross monthly income limits table.", score=0.95),
        _chunk("nc-fns-overview", text="Program overview.", score=0.7),
    ]
    with (
        patch("src.retrieval.retrieve.ensure_index"),
        patch("src.retrieval.retrieve.vector_index_ready", return_value=True),
        patch("src.retrieval.retrieve.embed_query", return_value=[0.1, 0.2]),
        patch("src.retrieval.retrieve.make_client", return_value=MagicMock()),
        patch("src.retrieval.retrieve.search", return_value=hits),
        patch("src.retrieval.retrieve.get_settings") as gs,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        gs.return_value.retrieval_top_k = 3
        cites = retrieve("food stamp income cutoff", limit=2)
    assert len(cites) == 2
    assert cites[0].source_id == "nc-fns-income-limits"
    assert "Gross monthly" in cites[0].snippet


def test_retrieve_by_source_ids_prefers_listed() -> None:
    preferred = [_chunk("agent-disclaimer", text="Disclaimer text.", score=0.5)]
    open_hits = [
        _chunk("nc-fns-income-limits", text="Income table.", score=0.99),
        _chunk("agent-disclaimer", text="Disclaimer text.", score=0.5),
    ]

    def _search(
        _client: object,
        _vector: list[float],
        *,
        limit: int = 3,
        source_ids: list[str] | None = None,
    ) -> list[StoredChunk]:
        if source_ids:
            return preferred
        return open_hits

    with (
        patch("src.retrieval.retrieve.ensure_index"),
        patch("src.retrieval.retrieve.vector_index_ready", return_value=True),
        patch("src.retrieval.retrieve.embed_query", return_value=[0.1]),
        patch("src.retrieval.retrieve.make_client", return_value=MagicMock()),
        patch("src.retrieval.retrieve.search", side_effect=_search),
        patch("src.retrieval.retrieve.get_settings") as gs,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        gs.return_value.retrieval_top_k = 3
        cites = retrieve_supporting_policy(
            ["agent-disclaimer", "nc-fns-income-limits"],
            user_query="eligibility",
            limit=2,
        )
    assert cites[0].source_id == "agent-disclaimer"
    assert any(c.source_id == "nc-fns-income-limits" for c in cites)


def test_retrieve_respects_limit() -> None:
    hits = [_chunk(f"src-{i}", text=f"body {i}", score=1.0 - i * 0.01) for i in range(5)]
    with (
        patch("src.retrieval.retrieve.ensure_index"),
        patch("src.retrieval.retrieve.vector_index_ready", return_value=True),
        patch("src.retrieval.retrieve.embed_query", return_value=[0.1]),
        patch("src.retrieval.retrieve.make_client", return_value=MagicMock()),
        patch("src.retrieval.retrieve.search", return_value=hits),
        patch("src.retrieval.retrieve.get_settings") as gs,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        gs.return_value.retrieval_top_k = 3
        cites = retrieve("query", limit=2)
    assert len(cites) == 2


def test_format_citations() -> None:
    text = format_citations(
        [
            Citation(
                source_id="x",
                title="T",
                url="https://e.x",
                snippet="s",
                effective_from="2025-01-01",
            )
        ]
    )
    assert "Sources:" in text
    assert "[x]" in text
    assert "https://e.x" in text


def test_retrieve_returns_empty_on_embed_failure() -> None:
    with (
        patch("src.retrieval.retrieve.ensure_index"),
        patch("src.retrieval.retrieve.embed_query", side_effect=RuntimeError("api down")),
        patch("src.retrieval.retrieve.get_settings") as gs,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        assert retrieve("anything") == []
