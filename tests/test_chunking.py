"""Markdown chunking (no network)."""

from __future__ import annotations

from src.retrieval.chunking import chunk_markdown


def test_chunk_splits_on_headings() -> None:
    text = (
        "# Title\n\nIntro para.\n\n## Section A\n\nBody A.\n\n## Section B\n\nBody B long enough."
    )
    chunks = chunk_markdown(text, max_chars=500)
    assert len(chunks) >= 2
    joined = " ".join(c.text for c in chunks)
    assert "Section A" in joined
    assert "Section B" in joined


def test_chunk_splits_long_paragraph() -> None:
    long = "word " * 200
    chunks = chunk_markdown(long, max_chars=80)
    assert len(chunks) > 1
    assert all(len(c.text) <= 80 for c in chunks)


def test_empty_text() -> None:
    assert chunk_markdown("   ") == []
