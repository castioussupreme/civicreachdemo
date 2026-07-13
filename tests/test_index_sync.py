"""Incremental index sync (Qdrant + embeddings mocked)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.retrieval.chunking import chunk_markdown
from src.retrieval.index import (
    SyncResult,
    format_sync_summary,
    reset_index_flag,
    sync_knowledge_index,
)
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


def _program_with_files(*files: str) -> MagicMock:
    """Program mock whose knowledge_dir / file resolves to an existing path for listed files."""
    knowledge_dir = MagicMock()

    def _div(name: object) -> MagicMock:
        path = MagicMock()
        path.is_file.return_value = str(name) in files or True
        # Prefer exact file names from SourceDoc.file
        path.is_file.return_value = True
        return path

    knowledge_dir.__truediv__ = MagicMock(side_effect=_div)
    program = MagicMock()
    program.knowledge_dir = knowledge_dir
    return program


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
        patch(
            "src.retrieval.index.list_indexed_source_ids",
            return_value={doc.id},
        ),
        patch("src.retrieval.index.list_enabled_slugs", return_value=["nc-fns"]),
        patch("src.retrieval.index.get_program", return_value=_program_with_files(doc.file)),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.skipped == 1
    assert result.reembedded == 0
    assert result.deleted == 0
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
        patch(
            "src.retrieval.index.list_indexed_source_ids",
            return_value={doc.id},
        ),
        patch("src.retrieval.index.list_enabled_slugs", return_value=["nc-fns"]),
        patch("src.retrieval.index.get_program", return_value=_program_with_files(doc.file)),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.reembedded == 1
    assert result.skipped == 0
    assert result.deleted == 0
    assert result.chunks_upserted == n
    # delete_source once before upsert for reembed; not for orphans
    assert delete.call_count == 1
    upsert.assert_called_once()
    embed.assert_called_once()


def test_sync_deletes_orphans() -> None:
    client = MagicMock()
    doc = _doc()
    knowledge_dir = MagicMock()
    # path.is_file() True for present doc
    present_path = MagicMock()
    present_path.is_file.return_value = True
    knowledge_dir.__truediv__ = MagicMock(return_value=present_path)
    program = MagicMock()
    program.knowledge_dir = knowledge_dir

    with (
        patch("src.retrieval.index.get_settings") as gs,
        patch("src.retrieval.index.make_client", return_value=client),
        patch("src.retrieval.index.ensure_collection"),
        patch("src.retrieval.index.load_corpus", return_value=(doc,)),
        patch("src.retrieval.index.source_hash_in_store", return_value=True),
        patch(
            "src.retrieval.index.list_indexed_source_ids",
            return_value={doc.id, "gone-source"},
        ),
        patch("src.retrieval.index.delete_source") as delete,
        patch("src.retrieval.index.list_enabled_slugs", return_value=["nc-fns"]),
        patch("src.retrieval.index.get_program", return_value=program),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.deleted == 1
    delete.assert_called()
    assert delete.call_args.args[1] == "gone-source"


def test_sync_deletes_when_expected_file_missing() -> None:
    """Manifest lists a source but the file is gone — remove from index and count deleted."""
    client = MagicMock()
    doc = _doc(source_id="vanished-doc")
    knowledge_dir = MagicMock()
    missing_path = MagicMock()
    missing_path.is_file.return_value = False
    knowledge_dir.__truediv__ = MagicMock(return_value=missing_path)
    program = MagicMock()
    program.knowledge_dir = knowledge_dir

    with (
        patch("src.retrieval.index.get_settings") as gs,
        patch("src.retrieval.index.make_client", return_value=client),
        patch("src.retrieval.index.ensure_collection"),
        patch("src.retrieval.index.load_corpus", return_value=(doc,)),
        patch("src.retrieval.index.embed_texts") as embed,
        patch(
            "src.retrieval.index.list_indexed_source_ids",
            return_value={"vanished-doc"},
        ),
        patch("src.retrieval.index.delete_source") as delete,
        patch("src.retrieval.index.list_enabled_slugs", return_value=["nc-fns"]),
        patch("src.retrieval.index.get_program", return_value=program),
    ):
        gs.return_value.effective_qdrant_url.return_value = "http://localhost:6333"
        result = sync_knowledge_index()
    assert result.deleted == 1
    assert result.reembedded == 0
    embed.assert_not_called()
    delete.assert_called()
    assert delete.call_args.args[1] == "vanished-doc"


def test_format_sync_summary_always_includes_deleted() -> None:
    line = format_sync_summary(SyncResult(skipped=0, reembedded=12, deleted=0, chunks_upserted=40))
    assert line == ("Knowledge RAG index: skipped=0 reembedded=12 deleted=0 chunks=40")
    assert "orphans" not in line
