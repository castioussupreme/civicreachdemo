"""CalFresh knowledge dual-copy and manifest consistency (pack-local)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.eligibility.ruleset import load_ruleset
from src.programs.registry import get_program, load_all_rulesets

PACK = Path(__file__).resolve().parents[1]
KNOWLEDGE = PACK / "knowledge"


def test_manifest_lists_expected_sources() -> None:
    manifest = json.loads((KNOWLEDGE / "manifest.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in manifest["sources"]}
    rs = load_ruleset("ca-calfresh", as_of=date(2026, 3, 1))
    assert rs.source_id in ids
    assert "calfresh-overview" in ids
    for src in manifest["sources"]:
        path = KNOWLEDGE / src["file"]
        assert path.is_file(), f"missing knowledge file {src['file']}"
        assert path.read_text(encoding="utf-8").strip()


def test_isolation_marker_in_overview() -> None:
    prog = get_program("ca-calfresh")
    overview = (prog.knowledge_dir / "calfresh-overview.md").read_text(encoding="utf-8")
    assert "CALFRESH_MARKER" in overview


def test_income_doc_matches_ruleset_table() -> None:
    for rs in load_all_rulesets("ca-calfresh"):
        if rs.source_id != "calfresh-income-limits":
            continue
        path = KNOWLEDGE / "calfresh-income-limits.md"
        text = path.read_text(encoding="utf-8")
        assert rs.id in text or rs.effective_from in text
        table = rs.gross_income_table()
        assert table is not None
        for size, amount in table.items():
            pretty = f"${amount:,.0f}" if float(amount) == int(amount) else f"${amount}"
            assert pretty in text or pretty.replace(",", "") in text or str(int(amount)) in text, (
                f"{rs.id}: threshold for size {size} ({amount}) not found in {path.name}"
            )
        increment = rs.gross_income_increment()
        assert increment is not None
        assert str(int(increment)) in text
