"""Curated knowledge base consistency with the versioned ruleset."""

from __future__ import annotations

import json
from pathlib import Path

from src.eligibility.ruleset import RULESET

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "programs" / "nc-fns" / "knowledge"


def test_manifest_lists_expected_sources() -> None:
    manifest = json.loads((KNOWLEDGE / "manifest.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in manifest["sources"]}
    assert RULESET.source_id in ids
    assert "agent-disclaimer" in ids
    assert "nc-fns-general-requirements" in ids
    assert "nc-fns-gross-income-tests" in ids
    for src in manifest["sources"]:
        path = KNOWLEDGE / src["file"]
        assert path.is_file(), f"missing knowledge file {src['file']}"
        assert path.read_text(encoding="utf-8").strip()


def test_gross_income_tests_doc_explains_200_vs_130() -> None:
    """RAG fodder for 'which test?' — no second dollar table (math stays on 200% ruleset)."""
    text = (KNOWLEDGE / "nc-fns-gross-income-tests.md").read_text(encoding="utf-8")
    assert "200%" in text
    assert "130%" in text
    assert "DSS" in text
    assert "does **not**" in text or "does not" in text.lower()
    assert "morefood.org" in text
    # No parallel 130% dollar schedule — math stays on the 200% RULESET table only
    assert "$" not in text


def test_income_doc_matches_ruleset_table() -> None:
    """
    Spot-check: RULESET amounts appear in knowledge/nc-fns-income-limits.md.

    Dual copy is intentional (math in code, table for RAG). Agents must update
    both — see AGENTS.md. This is a soft guard, not a full table parser.
    """
    text = (KNOWLEDGE / "nc-fns-income-limits.md").read_text(encoding="utf-8")
    assert RULESET.effective_from in text or "2025-10-01" in text or "October 1, 2025" in text
    for size, amount in RULESET.max_gross_monthly_by_size.items():
        # Doc uses $2,610 style for small sizes
        pretty = f"${amount:,.0f}" if amount == int(amount) else f"${amount}"
        alt = f"$ {amount:,.0f}" if amount == int(amount) else None
        assert (
            pretty in text
            or pretty.replace(",", "") in text
            or (alt is not None and alt in text)
            or str(int(amount)) in text
        ), f"threshold for size {size} ({amount}) not found in income doc"
    assert str(int(RULESET.additional_member_increment)) in text
