"""Doc effective-window filtering within a program silo."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.retrieval.qdrant_store import StoredChunk, doc_covers_as_of
from src.retrieval.retrieve import retrieve


def test_doc_covers_as_of_open_ended() -> None:
    assert doc_covers_as_of(effective_from=None, effective_to=None, as_of="2026-01-01")
    assert doc_covers_as_of(effective_from="2026-10-01", effective_to=None, as_of="2027-01-01")
    assert not doc_covers_as_of(effective_from="2026-10-01", effective_to=None, as_of="2026-09-30")


def test_doc_covers_as_of_closed_window() -> None:
    assert doc_covers_as_of(
        effective_from="2025-10-01",
        effective_to="2026-09-30",
        as_of="2026-03-01",
    )
    assert not doc_covers_as_of(
        effective_from="2025-10-01",
        effective_to="2026-09-30",
        as_of="2026-10-01",
    )


def _chunk(
    source_id: str,
    *,
    score: float = 0.9,
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> StoredChunk:
    return StoredChunk(
        source_id=source_id,
        title=source_id,
        url="https://example.com",
        chunk_text=f"text for {source_id}",
        content_hash="h",
        chunk_index=0,
        score=score,
        program_slug="nc-fns",
        effective_from=effective_from,
        effective_to=effective_to,
    )


def test_retrieve_filters_docs_by_as_of() -> None:
    """Within program silo, expired FY table should not surface after rollover."""
    hits = [
        _chunk(
            "nc-fns-income-limits-2024",
            score=0.99,
            effective_from="2024-10-01",
            effective_to="2025-09-30",
        ),
        _chunk(
            "nc-fns-income-limits",
            score=0.95,
            effective_from="2025-10-01",
            effective_to="2026-09-30",
        ),
        _chunk("nc-fns-overview", score=0.5, effective_from=None, effective_to=None),
    ]

    def _search(
        _client: object,
        _vector: list[float],
        *,
        program_slug: str = "",
        limit: int = 3,
        source_ids: list[str] | None = None,
        as_of: str | None = None,
    ) -> list[StoredChunk]:
        assert program_slug == "nc-fns"
        out: list[StoredChunk] = []
        for h in hits:
            if source_ids and h.source_id not in source_ids:
                continue
            if as_of and not doc_covers_as_of(
                effective_from=h.effective_from,
                effective_to=h.effective_to,
                as_of=as_of,
            ):
                continue
            out.append(h)
            if len(out) >= limit:
                break
        return out

    with (
        patch("src.retrieval.retrieve.ensure_index"),
        patch("src.retrieval.retrieve.vector_index_ready", return_value=True),
        patch("src.retrieval.retrieve.embed_query", return_value=[0.1]),
        patch("src.retrieval.retrieve.make_client", return_value=MagicMock()),
        patch("src.retrieval.retrieve.search", side_effect=_search),
        patch("src.retrieval.retrieve.get_settings") as gs,
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        gs.return_value.retrieval_top_k = 5
        prior = retrieve(
            "income limits",
            program_slug="nc-fns",
            as_of="2025-03-01",
            limit=5,
        )
        current = retrieve(
            "income limits",
            program_slug="nc-fns",
            as_of="2026-03-01",
            limit=5,
        )

    prior_ids = {c.source_id for c in prior}
    current_ids = {c.source_id for c in current}
    assert "nc-fns-income-limits-2024" in prior_ids
    assert "nc-fns-income-limits" not in prior_ids
    assert "nc-fns-income-limits" in current_ids
    assert "nc-fns-income-limits-2024" not in current_ids
    assert "nc-fns-overview" in prior_ids and "nc-fns-overview" in current_ids
