"""Smoke runner unit tests (API client stubbed — no live network)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:18080")

from src.smoke import (
    EXPECTED_MONTHLY,
    EXPECTED_STATUS,
    EXPECTED_THRESHOLD,
    SCENARIOS,
    SmokeScenario,
    _injection_extras,
    run_scenario,
    run_smoke,
)
from src.state.models import AssessmentStatus


def _api_mock(*, chat_return: dict[str, object]) -> MagicMock:
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi")
    api.chat.return_value = chat_return
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)
    return api


def test_scenarios_cover_expected_names() -> None:
    names = {s.name for s in SCENARIOS}
    assert names == {"happy", "net", "individual", "student", "injection"}
    for s in SCENARIOS:
        assert s.script.name.endswith(".txt")


def test_run_scenario_pass(tmp_path: Path) -> None:
    script = tmp_path / "s.txt"
    script.write_text("hi\n", encoding="utf-8")
    scenario = SmokeScenario(
        name="happy",
        script=script,
        expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
        expect_household=2,
        expect_monthly=EXPECTED_MONTHLY,
        expect_threshold=EXPECTED_THRESHOLD,
    )
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "done",
            "stage": "assessed",
            "assessment": {
                "status": EXPECTED_STATUS.value,
                "household_size": 2,
                "normalized_gross_monthly": EXPECTED_MONTHLY,
                "threshold_used": EXPECTED_THRESHOLD,
            },
        }
    )
    assert run_scenario(api, scenario) is True


def test_run_scenario_fails_without_assessment(tmp_path: Path) -> None:
    script = tmp_path / "s.txt"
    script.write_text("hello\n", encoding="utf-8")
    scenario = SmokeScenario(
        name="happy",
        script=script,
        expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
    )
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "more?",
            "stage": "collecting",
            "assessment": None,
        }
    )
    assert run_scenario(api, scenario) is False


def test_run_scenario_fails_wrong_status(tmp_path: Path) -> None:
    script = tmp_path / "s.txt"
    script.write_text("one\n", encoding="utf-8")
    scenario = SmokeScenario(
        name="happy",
        script=script,
        expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
        expect_household=2,
        expect_monthly=EXPECTED_MONTHLY,
        expect_threshold=EXPECTED_THRESHOLD,
    )
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "nope",
            "assessment": {
                "status": "likely_ineligible",
                "household_size": 2,
                "normalized_gross_monthly": EXPECTED_MONTHLY,
                "threshold_used": EXPECTED_THRESHOLD,
            },
        }
    )
    assert run_scenario(api, scenario) is False


def test_injection_extra_rejects_eligible() -> None:
    last = {
        "assessment": {"status": "likely_eligible"},
        "safety_action": "continue",
    }
    assert _injection_extras(last)


def test_run_smoke_all_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every scenario script and chat responses matching expectations."""
    stubs: list[SmokeScenario] = []
    for s in SCENARIOS:
        p = tmp_path / f"{s.name}.txt"
        p.write_text("turn\n", encoding="utf-8")
        stubs.append(
            SmokeScenario(
                name=s.name,
                script=p,
                expect_status=s.expect_status,
                expect_household=s.expect_household,
                expect_monthly=s.expect_monthly,
                expect_threshold=s.expect_threshold,
                extra_check=s.extra_check,
            )
        )

    responses = {
        "happy": {
            "status": "likely_eligible",
            "household_size": 2,
            "normalized_gross_monthly": 3000.0,
            "threshold_used": stubs[0].expect_threshold,
        },
        "net": {
            "status": "unable_to_determine",
            "household_size": 1,
            "normalized_gross_monthly": 2000.0,
            "threshold_used": stubs[1].expect_threshold,
        },
        "individual": {
            "status": "unable_to_determine",
            "household_size": 3,
            "normalized_gross_monthly": 2000.0,
            "threshold_used": stubs[2].expect_threshold,
        },
        "student": {
            "status": "unable_to_determine",
            "household_size": 1,
            "normalized_gross_monthly": 1500.0,
            "threshold_used": stubs[3].expect_threshold,
        },
        "injection": {
            "status": "likely_ineligible",
            "household_size": 1,
            "normalized_gross_monthly": 9000.0,
            "threshold_used": stubs[4].expect_threshold,
        },
    }

    call_i = {"n": 0}

    def chat(_msg: str, session_id: str = "", debug: bool = False) -> dict[str, object]:
        # one chat per scenario (scripts have 1 line each in this test)
        scenario = stubs[call_i["n"]]
        call_i["n"] += 1
        return {
            "session_id": "sid",
            "reply": "ok",
            "stage": "assessed",
            "assessment": responses[scenario.name],
        }

    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi")
    api.chat.side_effect = chat
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)

    with (
        patch("src.smoke.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.smoke.AgentApiClient", return_value=api),
    ):
        assert run_smoke(tuple(stubs)) == 0


def test_run_smoke_fails_if_any_scenario_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "only.txt"
    p.write_text("x\n", encoding="utf-8")
    scenarios = (
        SmokeScenario(
            name="happy",
            script=p,
            expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
            expect_household=2,
            expect_monthly=3000.0,
            expect_threshold=3526.0,
        ),
    )
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "x",
            "assessment": {
                "status": "unable_to_determine",
                "household_size": 2,
                "normalized_gross_monthly": 3000.0,
                "threshold_used": 3526.0,
            },
        }
    )
    with (
        patch("src.smoke.resolve_public_api_base", return_value="http://127.0.0.1:18080"),
        patch("src.smoke.AgentApiClient", return_value=api),
    ):
        assert run_smoke(scenarios) == 1
