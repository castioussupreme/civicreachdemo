"""Multi-program isolation: catalog, rulesets, and retrieve never cross silos."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from src.eligibility.engine import calculate_eligibility
from src.programs.registry import catalog_programs, get_program, resolve_ruleset
from src.retrieval.qdrant_store import StoredChunk
from src.retrieval.retrieve import retrieve
from src.state.models import CaseField, FieldStatus, fresh_case


def test_registry_lists_both_public_programs() -> None:
    entries = catalog_programs(q="", as_of=date(2026, 3, 1), limit=20)
    slugs = {e.slug for e in entries}
    assert "nc-fns" in slugs
    assert "ca-calfresh" in slugs


def test_catalog_typeahead_separates_programs() -> None:
    cal = catalog_programs(q="CalFresh", as_of=date(2026, 3, 1), limit=10)
    assert any(e.slug == "ca-calfresh" for e in cal)
    assert all(e.slug != "nc-fns" or "cal" in e.display_name.lower() for e in cal)
    # SNAP may match both aliases; NC-only query should prefer nc-fns
    nc = catalog_programs(q="North Carolina food", as_of=date(2026, 3, 1), limit=10)
    assert any(e.slug == "nc-fns" for e in nc)


def test_calfresh_ruleset_distinct_from_prior_nc_year() -> None:
    cal = resolve_ruleset("ca-calfresh", date(2026, 3, 1))
    nc_prior = resolve_ruleset("nc-fns", date(2025, 3, 1))
    nc_current = resolve_ruleset("nc-fns", date(2026, 3, 1))
    assert cal.id == "ca-calfresh-screening-2025-10"
    assert nc_prior.id == "nc-fns-screening-2024-10"
    assert nc_current.id == "nc-fns-screening-2025-10"
    # Prior-year NC table differs from current NC / CalFresh
    assert nc_prior.threshold_for_household(2) == 3408.0
    assert nc_current.threshold_for_household(2) == 3526.0
    assert cal.threshold_for_household(2) == 3526.0
    # Larger HH: CalFresh public chart differs slightly from NC MoreFood table
    assert cal.threshold_for_household(6) == 7192.0
    assert nc_current.threshold_for_household(6) == 7194.0


def test_calfresh_session_uses_calfresh_sources() -> None:
    case = fresh_case(program_slug="ca-calfresh", as_of="2026-03-01")
    assert case.program_slug == "ca-calfresh"
    assert case.ruleset_id == "ca-calfresh-screening-2025-10"
    case.lives_in_nc = CaseField(status=FieldStatus.KNOWN, value=True)
    case.household_size = CaseField(status=FieldStatus.KNOWN, value=2)
    case.normalized_gross_monthly = CaseField(status=FieldStatus.KNOWN, value=3000.0)
    result = calculate_eligibility(case)
    assert result.threshold_used == 3526.0
    assert result.status.value == "likely_eligible"
    assert "calfresh-income-limits" in result.source_ids
    assert "nc-fns-income-limits" not in result.source_ids


def test_calfresh_not_in_service_area_message() -> None:
    case = fresh_case(program_slug="ca-calfresh", as_of="2026-03-01")
    case.lives_in_nc = CaseField(status=FieldStatus.KNOWN, value=False)
    result = calculate_eligibility(case)
    assert result.status.value == "likely_ineligible"
    assert "California" in result.reasons[0]


def test_retrieve_never_returns_other_program_sources() -> None:
    nc_hits = [
        StoredChunk(
            source_id="nc-fns-income-limits",
            title="NC limits",
            url="https://morefood.org/",
            chunk_text="NC FNS gross monthly income limits table",
            content_hash="a",
            chunk_index=0,
            score=0.99,
            program_slug="nc-fns",
        ),
    ]
    cal_hits = [
        StoredChunk(
            source_id="calfresh-overview",
            title="CalFresh overview",
            url="https://www.cdss.ca.gov/calfresh",
            chunk_text="CALFRESH_MARKER isolation text",
            content_hash="b",
            chunk_index=0,
            score=0.99,
            program_slug="ca-calfresh",
        ),
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
        _ = source_ids, as_of, limit
        if program_slug == "nc-fns":
            return list(nc_hits)
        if program_slug == "ca-calfresh":
            return list(cal_hits)
        raise AssertionError(f"unexpected program_slug={program_slug!r}")

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
        nc_cites = retrieve("income limits", program_slug="nc-fns", limit=3)
        cal_cites = retrieve("income limits", program_slug="ca-calfresh", limit=3)

    nc_ids = {c.source_id for c in nc_cites}
    cal_ids = {c.source_id for c in cal_cites}
    assert "nc-fns-income-limits" in nc_ids
    assert "calfresh-overview" not in nc_ids
    assert "CALFRESH_MARKER" not in " ".join(c.snippet for c in nc_cites)
    assert "calfresh-overview" in cal_ids
    assert "nc-fns-income-limits" not in cal_ids


def test_calfresh_knowledge_markers() -> None:
    prog = get_program("ca-calfresh")
    overview = (prog.knowledge_dir / "calfresh-overview.md").read_text(encoding="utf-8")
    assert "CALFRESH_MARKER" in overview
    assert (prog.knowledge_dir / "manifest.json").is_file()
