"""Curated knowledge base consistency with the versioned ruleset."""

from __future__ import annotations

import json
from pathlib import Path

from src.eligibility.ruleset import RULESET

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"


def test_manifest_lists_expected_sources() -> None:
    manifest = json.loads((KNOWLEDGE / "manifest.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in manifest["sources"]}
    assert RULESET.source_id in ids
    assert "agent-disclaimer" in ids
    assert "nc-fns-general-requirements" in ids
    for src in manifest["sources"]:
        path = KNOWLEDGE / src["file"]
        assert path.is_file(), f"missing knowledge file {src['file']}"
        assert path.read_text(encoding="utf-8").strip()


def test_income_doc_matches_ruleset_table() -> None:
    """Spot-check public table values appear in curated income limits doc."""
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
