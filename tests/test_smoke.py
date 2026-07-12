"""Smoke runner unit tests (LLM/Redis stubbed — no live network)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from src.process_turn import TurnResult
from src.smoke import EXPECTED_MONTHLY, EXPECTED_STATUS, EXPECTED_THRESHOLD, run_smoke
from src.state.models import (
    Assessment,
    AssessmentStatus,
    CaseField,
    EligibilityCase,
    FieldStatus,
    Stage,
)
from tests.conftest import FakeSessionStore


def _assessed_case() -> EligibilityCase:
    case = EligibilityCase(stage=Stage.ASSESSED, turn_count=4)
    case.assessment = Assessment(
        status=EXPECTED_STATUS,
        reasons=["ok"],
        rule_version="test",
        source_ids=["agent-disclaimer"],
        threshold_used=EXPECTED_THRESHOLD,
        normalized_gross_monthly=EXPECTED_MONTHLY,
        household_size=2,
    )
    case.household_size = CaseField(status=FieldStatus.KNOWN, value=2)
    case.normalized_gross_monthly = CaseField(status=FieldStatus.KNOWN, value=EXPECTED_MONTHLY)
    return case


def test_smoke_pass_with_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("hi\nI live in NC alone making 3000 monthly gross\n", encoding="utf-8")
    store = FakeSessionStore()

    def fake_process(message: str, case: EligibilityCase) -> TurnResult:
        done = _assessed_case()
        return TurnResult(
            reply="done", case=done, safety_action="continue", assessment=done.assessment
        )

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.get_settings") as gs,
        patch("src.smoke.open_session_store", return_value=store),
        patch("src.smoke.process_turn", side_effect=fake_process),
    ):
        gs.return_value = MagicMock(
            openai_model="test-model",
            effective_redis_url=lambda: "redis://localhost:6379/0",
        )
        assert run_smoke() == 0


def test_smoke_fails_without_assessment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("hello only\n", encoding="utf-8")
    store = FakeSessionStore()

    def fake_process(message: str, case: EligibilityCase) -> TurnResult:
        case.turn_count += 1
        return TurnResult(reply="more?", case=case, safety_action="continue")

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.get_settings") as gs,
        patch("src.smoke.open_session_store", return_value=store),
        patch("src.smoke.process_turn", side_effect=fake_process),
    ):
        gs.return_value = MagicMock(
            openai_model="test-model",
            effective_redis_url=lambda: "redis://localhost:6379/0",
        )
        assert run_smoke() == 1


def test_smoke_fails_wrong_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "happy.txt"
    script.write_text("one\n", encoding="utf-8")
    store = FakeSessionStore()

    def fake_process(message: str, case: EligibilityCase) -> TurnResult:
        done = _assessed_case()
        assert done.assessment is not None
        done.assessment.status = AssessmentStatus.LIKELY_INELIGIBLE
        return TurnResult(
            reply="nope", case=done, safety_action="continue", assessment=done.assessment
        )

    monkeypatch.setattr("src.smoke.HAPPY_PATH", script)
    with (
        patch("src.smoke.get_settings") as gs,
        patch("src.smoke.open_session_store", return_value=store),
        patch("src.smoke.process_turn", side_effect=fake_process),
    ):
        gs.return_value = MagicMock(
            openai_model="test-model",
            effective_redis_url=lambda: "redis://localhost:6379/0",
        )
        assert run_smoke() == 1
