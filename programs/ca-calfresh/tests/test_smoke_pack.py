"""CalFresh pack smoke scenarios are loadable and complete (parity with nc-fns)."""

from __future__ import annotations

from pathlib import Path

from src.smoke import load_pack_scenarios
from src.state.models import AssessmentStatus

PACK = Path(__file__).resolve().parents[1]

# Same scenario set as nc-fns (student expectation differs: no student_soft module).
EXPECTED_SCENARIOS = frozenset({"happy", "net", "individual", "student", "injection"})


def test_smoke_scripts_exist() -> None:
    scenarios = load_pack_scenarios("ca-calfresh")
    names = {s.name for s in scenarios}
    assert names == EXPECTED_SCENARIOS
    for s in scenarios:
        assert s.script.is_file(), f"missing {s.script}"
        assert s.script.is_relative_to(PACK / "smoke")


def test_optional_adversarial_script_exists() -> None:
    """CLI-only messy path (same role as nc-fns/smoke/adversarial.txt)."""
    path = PACK / "smoke" / "adversarial.txt"
    assert path.is_file()
    text = path.read_text(encoding="utf-8").lower()
    assert "california" in text
    assert "benefitscal" in text or "application" in text


def test_happy_scenario_expectations() -> None:
    scenarios = load_pack_scenarios("ca-calfresh")
    happy = next(s for s in scenarios if s.name == "happy")
    assert happy.expect_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert happy.expect_household == 2
    assert happy.expect_monthly == 3000.0
    assert happy.expect_threshold == 3526.0


def test_net_scenario_expectations() -> None:
    net = next(s for s in load_pack_scenarios("ca-calfresh") if s.name == "net")
    assert net.expect_status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert net.expect_household == 1
    assert net.expect_monthly == 2000.0
    assert net.expect_threshold == 2610.0


def test_individual_scenario_expectations() -> None:
    ind = next(s for s in load_pack_scenarios("ca-calfresh") if s.name == "individual")
    assert ind.expect_status == AssessmentStatus.UNABLE_TO_DETERMINE
    assert ind.expect_household == 3
    assert ind.expect_monthly == 2000.0
    assert ind.expect_threshold == 4442.0


def test_student_scenario_expectations_no_soft_module() -> None:
    """Without student_soft_unable, student under the table is still likely eligible."""
    student = next(s for s in load_pack_scenarios("ca-calfresh") if s.name == "student")
    assert student.expect_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert student.expect_household == 1
    assert student.expect_monthly == 1500.0
    assert student.expect_threshold == 2610.0


def test_injection_scenario_expectations() -> None:
    inj = next(s for s in load_pack_scenarios("ca-calfresh") if s.name == "injection")
    assert inj.expect_status == AssessmentStatus.LIKELY_INELIGIBLE
    assert inj.reject_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert inj.expect_household == 1
    assert inj.expect_monthly == 9000.0
    assert inj.expect_threshold == 2610.0


def test_smoke_scripts_follow_planner_order_comments() -> None:
    """Happy intro must not bury residency (would desync fixed scripts)."""
    happy = (PACK / "smoke" / "happy.txt").read_text(encoding="utf-8")
    lines = [
        ln.strip() for ln in happy.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "california" not in lines[0].lower()
    assert "california" in lines[1].lower()


def test_all_scripts_residency_before_household_facts() -> None:
    """Each fixed script: first content line is residency (or injection), not buried CA+HH."""
    for name in ("net", "individual", "student"):
        path = PACK / "smoke" / f"{name}.txt"
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert "california" in lines[0].lower(), f"{name}: first line should be residency"
        # Household size should not appear before residency line
        assert "three" not in lines[0].lower()
        assert "$" not in lines[0]


def test_injection_script_leads_with_injection() -> None:
    path = PACK / "smoke" / "injection.txt"
    lines = [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "ignore" in lines[0].lower()
    assert "california" in lines[1].lower()
