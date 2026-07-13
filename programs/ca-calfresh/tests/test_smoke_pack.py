"""CalFresh pack smoke scenarios are loadable."""

from __future__ import annotations

from pathlib import Path

from src.smoke import load_pack_scenarios
from src.state.models import AssessmentStatus

PACK = Path(__file__).resolve().parents[1]


def test_smoke_scripts_exist() -> None:
    scenarios = load_pack_scenarios("ca-calfresh")
    names = {s.name for s in scenarios}
    assert names == {"happy"}
    for s in scenarios:
        assert s.script.is_file()
        assert s.script.is_relative_to(PACK / "smoke")


def test_happy_scenario_expectations() -> None:
    happy = next(s for s in load_pack_scenarios("ca-calfresh") if s.name == "happy")
    assert happy.expect_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert happy.expect_household == 2
    assert happy.expect_monthly == 3000.0
    assert happy.expect_threshold == 3526.0


def test_smoke_scripts_follow_planner_order_comments() -> None:
    """Happy intro must not bury residency (would desync fixed scripts)."""
    happy = (PACK / "smoke" / "happy.txt").read_text(encoding="utf-8")
    lines = [
        ln.strip() for ln in happy.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "california" not in lines[0].lower()
    assert "california" in lines[1].lower()
