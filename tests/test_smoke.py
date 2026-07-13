"""Smoke runner unit tests (API client stubbed — no live network)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:18080")

from src.smoke import SmokeScenario, load_pack_scenarios, run_scenario, run_smoke
from src.state.models import AssessmentStatus


def _api_mock(*, chat_return: dict[str, object]) -> MagicMock:
    api = MagicMock()
    api.health.return_value = {"status": "ok"}
    api.create_session.return_value = ("sid", "hi", {"program_slug": "nc-fns"})
    api.chat.return_value = chat_return
    api.__enter__ = MagicMock(return_value=api)
    api.__exit__ = MagicMock(return_value=False)
    return api


def test_load_pack_scenarios_nc_fns() -> None:
    scenarios = load_pack_scenarios("nc-fns")
    names = {s.name for s in scenarios}
    assert names == {"happy", "net", "individual", "student", "injection"}
    happy = next(s for s in scenarios if s.name == "happy")
    assert happy.expect_status == AssessmentStatus.LIKELY_ELIGIBLE
    assert happy.expect_threshold == 3526.0


def test_run_scenario_pass(tmp_path: Path) -> None:
    script = tmp_path / "s.txt"
    script.write_text("hi\n", encoding="utf-8")
    scenario = SmokeScenario(
        name="happy",
        script=script,
        expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
        expect_household=2,
        expect_monthly=3000.0,
        expect_threshold=3526.0,
    )
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "done",
            "stage": "assessed",
            "assessment": {
                "status": "likely_eligible",
                "household_size": 2,
                "normalized_gross_monthly": 3000.0,
                "threshold_used": 3526.0,
            },
        }
    )
    assert run_scenario(api, scenario, program_slug="nc-fns") is True


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
    assert run_scenario(api, scenario, program_slug="nc-fns") is False


def test_run_smoke_all_pass(tmp_path: Path) -> None:
    script = tmp_path / "s.txt"
    script.write_text("turn\n", encoding="utf-8")
    scenarios = [
        SmokeScenario(
            name="happy",
            script=script,
            expect_status=AssessmentStatus.LIKELY_ELIGIBLE,
            expect_household=2,
            expect_monthly=3000.0,
            expect_threshold=3526.0,
        )
    ]
    api = _api_mock(
        chat_return={
            "session_id": "sid",
            "reply": "ok",
            "assessment": {
                "status": "likely_eligible",
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
        assert run_smoke(program_slug="nc-fns", scenarios=scenarios) == 0
