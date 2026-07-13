"""NC FNS pack smoke scenarios are loadable and complete."""

from __future__ import annotations

from pathlib import Path

from src.smoke import load_pack_scenarios
from src.state.models import AssessmentStatus

PACK = Path(__file__).resolve().parents[1]


def test_smoke_scripts_exist() -> None:
    scenarios = load_pack_scenarios("nc-fns")
    names = {s.name for s in scenarios}
    assert names == {"happy", "net", "individual", "student", "injection"}
    for s in scenarios:
        assert s.script.is_file(), f"missing {s.script}"
        assert s.script.is_relative_to(PACK / "smoke")


def test_happy_scenario_expectations() -> None:
    scenarios = load_pack_scenarios("nc-fns")
    happy = next(s for s in scenarios if s.name == "happy")
    assert happy.expect_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert happy.expect_household == 2
    assert happy.expect_monthly == 3000.0
    assert happy.expect_threshold == 3526.0


def test_net_scenario_expectations() -> None:
    net = next(s for s in load_pack_scenarios("nc-fns") if s.name == "net")
    assert net.expect_status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert net.expect_household == 1
    assert net.expect_monthly == 2000.0
    assert net.expect_threshold == 2610.0


def test_individual_scenario_expectations() -> None:
    ind = next(s for s in load_pack_scenarios("nc-fns") if s.name == "individual")
    assert ind.expect_status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert ind.expect_household == 3
    assert ind.expect_monthly == 2000.0


def test_student_scenario_expectations() -> None:
    student = next(s for s in load_pack_scenarios("nc-fns") if s.name == "student")
    assert student.expect_status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert student.expect_household == 1
    assert student.expect_monthly == 1500.0


def test_injection_scenario_expectations() -> None:
    inj = next(s for s in load_pack_scenarios("nc-fns") if s.name == "injection")
    assert inj.expect_status == AssessmentStatus.LIKELY_INELIGIBLE
    assert inj.reject_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert inj.expect_household == 1
    assert inj.expect_monthly == 9000.0


def test_optional_adversarial_script_exists() -> None:
    path = PACK / "smoke" / "adversarial.txt"
    assert path.is_file()
    text = path.read_text(encoding="utf-8").lower()
    assert "north carolina" in text


def test_smoke_scripts_follow_planner_order_comments() -> None:
    """Happy intro must not bury residency (would desync fixed scripts)."""
    happy = (PACK / "smoke" / "happy.txt").read_text(encoding="utf-8")
    lines = [
        ln.strip() for ln in happy.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    assert lines[0].lower().find("north carolina") < 0
    assert "north carolina" in lines[1].lower()
