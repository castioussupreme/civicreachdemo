"""NC FNS knowledge dual-copy and manifest consistency (pack-local)."""

from __future__ import annotations

import json
from pathlib import Path

from src.eligibility.ruleset import load_ruleset
from src.programs.registry import load_all_rulesets

PACK = Path(__file__).resolve().parents[1]
KNOWLEDGE = PACK / "knowledge"


def test_manifest_lists_expected_sources() -> None:
    manifest = json.loads((KNOWLEDGE / "manifest.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in manifest["sources"]}
    assert load_ruleset("nc-fns").source_id in ids
    assert "agent-disclaimer" in ids
    assert "nc-fns-general-requirements" in ids
    assert "nc-fns-gross-income-tests" in ids
    assert "nc-fns-income-limits-2024" in ids
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
    assert "$" not in text


def test_income_doc_matches_ruleset_table() -> None:
    """
    Dual copy: each ruleset version's amounts appear in its knowledge income doc.
    """
    for rs in load_all_rulesets("nc-fns"):
        if rs.source_id == "nc-fns-income-limits":
            path = KNOWLEDGE / "nc-fns-income-limits.md"
        elif rs.source_id == "nc-fns-income-limits-2024":
            path = KNOWLEDGE / "nc-fns-income-limits-2024.md"
        else:
            continue
        text = path.read_text(encoding="utf-8")
        assert rs.id in text or rs.effective_from in text
        table = rs.gross_income_table()
        assert table is not None, f"{rs.id}: missing gross_income_limit requirement"
        for size, amount in table.items():
            pretty = f"${amount:,.0f}" if float(amount) == int(amount) else f"${amount}"
            assert pretty in text or pretty.replace(",", "") in text or str(int(amount)) in text, (
                f"{rs.id}: threshold for size {size} ({amount}) not found in {path.name}"
            )
        increment = rs.gross_income_increment()
        assert increment is not None
        assert str(int(increment)) in text
