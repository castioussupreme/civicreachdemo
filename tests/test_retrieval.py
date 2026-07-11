"""Knowledge retrieval (deterministic, no LLM)."""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.retrieval.kb import (
    format_citations,
    get_by_id,
    load_corpus,
    retrieve,
    retrieve_supporting_policy,
)


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


def test_retrieve_income() -> None:
    hits = retrieve("gross monthly income limits household", limit=3)
    assert hits
    assert any(h.source_id == "nc-fns-income-limits" for h in hits)
    assert hits[0].snippet


def test_retrieve_student_query() -> None:
    hits = retrieve("college student exemption work study", limit=3)
    assert hits
    assert any(h.source_id == "nc-fns-student-rules" for h in hits)


def test_retrieve_by_source_ids_prefers_listed() -> None:
    hits = retrieve_supporting_policy(
        ["agent-disclaimer", "nc-fns-income-limits"],
        user_query="eligibility",
        limit=2,
    )
    assert len(hits) <= 2
    assert hits[0].source_id in {"agent-disclaimer", "nc-fns-income-limits"}


def test_retrieve_respects_limit() -> None:
    hits = retrieve("food nutrition services eligibility household income", limit=1)
    assert len(hits) == 1


def test_format_citations() -> None:
    hits = retrieve("income limits", limit=1)
    text = format_citations(hits)
    assert "Sources:" in text
    assert hits[0].source_id in text
    assert format_citations([]) == ""
