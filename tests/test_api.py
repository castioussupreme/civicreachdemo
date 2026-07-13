"""HTTP API (process_turn stubbed; Redis store faked)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from fastapi.testclient import TestClient
from src.api.app import app
from src.process_turn import TurnResult
from src.state.models import (
    Assessment,
    AssessmentStatus,
    CaseField,
    EligibilityCase,
    FieldStatus,
)


def _fake_process(message: str, case: EligibilityCase) -> TurnResult:
    case.turn_count += 1
    if "nc" in message.lower() or "north carolina" in message.lower():
        case.lives_in_service_area = CaseField(status=FieldStatus.KNOWN, value=True)
    return TurnResult(
        reply=f"echo:{message}",
        case=case,
        safety_action="continue",
        assessment=None,
        debug={"turn": case.turn_count},
    )


def _fake_process_with_assessment(message: str, case: EligibilityCase) -> TurnResult:
    case.turn_count += 1
    case.lives_in_service_area = CaseField(status=FieldStatus.KNOWN, value=True)
    assessment = Assessment(
        status=AssessmentStatus.LIKELY_ELIGIBLE,
        reasons=["test"],
        rule_version="test-rules",
        source_ids=["nc-fns-income-limits", "agent-disclaimer"],
    )
    case.assessment = assessment
    return TurnResult(
        reply="assessed",
        case=case,
        safety_action="continue",
        assessment=assessment,
        debug={"assessed": True},
    )


@pytest.mark.usefixtures("fake_session_store")
def test_health_lists_endpoints_and_redis() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert "openai_model" in body
        assert "active_programs" in body
        assert body["resources"]["sessions"] == "redis"
        assert "redis_url" in body["resources"]
        assert "default_program" not in body
        for key in ("health", "openapi", "programs", "chat", "create_session", "state", "reset"):
            assert key in body["endpoints"]
        assert body["active_programs"] >= 1


@pytest.mark.usefixtures("fake_session_store")
def test_list_programs_search() -> None:
    with TestClient(app) as client:
        all_p = client.get("/api/programs")
        assert all_p.status_code == 200
        assert any(p["slug"] == "nc-fns" for p in all_p.json())
        snap = client.get("/api/programs", params={"q": "SNAP"})
        assert snap.status_code == 200
        assert len(snap.json()) >= 1


@pytest.mark.usefixtures("fake_session_store")
def test_session_requires_program_slug() -> None:
    with TestClient(app) as client:
        bad = client.post("/api/session", json={})
        assert bad.status_code == 422


@pytest.mark.usefixtures("fake_session_store")
def test_create_chat_state_reset_flow() -> None:
    with (
        patch("src.api.app.process_turn", side_effect=_fake_process),
        TestClient(app) as client,
    ):
        created = client.post("/api/session", json={"program_slug": "nc-fns"})
        assert created.status_code == 200
        sid = created.json()["session_id"]
        assert created.json()["opening_message"]
        assert created.json()["program_slug"] == "nc-fns"
        assert created.json()["ruleset_id"]

        chat = client.post(
            "/api/chat",
            json={"session_id": sid, "message": "I live in North Carolina"},
        )
        assert chat.status_code == 200
        data = chat.json()
        assert data["session_id"] == sid
        assert data["reply"].startswith("echo:")

        state = client.get(f"/api/session/{sid}/state")
        assert state.status_code == 200
        assert state.json()["state"]["lives_in_service_area"]["value"] is True

        reset = client.post(f"/api/session/{sid}/reset", json={})
        assert reset.status_code == 200

        state2 = client.get(f"/api/session/{sid}/state")
        assert "lives_in_service_area" not in state2.json()["state"]


@pytest.mark.usefixtures("fake_session_store")
def test_chat_requires_session_id() -> None:
    with TestClient(app) as client:
        chat = client.post("/api/chat", json={"message": "hello"})
        assert chat.status_code == 400


@pytest.mark.usefixtures("fake_session_store")
def test_chat_debug_query_returns_debug() -> None:
    with (
        patch("src.api.app.process_turn", side_effect=_fake_process),
        TestClient(app) as client,
    ):
        sid = client.post("/api/session", json={"program_slug": "nc-fns"}).json()["session_id"]
        chat = client.post(
            "/api/chat?debug=true",
            json={"session_id": sid, "message": "hi"},
        )
        assert chat.status_code == 200
        assert chat.json()["debug"] == {"turn": 1}


@pytest.mark.usefixtures("fake_session_store")
def test_chat_includes_assessment_status() -> None:
    with (
        patch("src.api.app.process_turn", side_effect=_fake_process_with_assessment),
        TestClient(app) as client,
    ):
        sid = client.post("/api/session", json={"program_slug": "nc-fns"}).json()["session_id"]
        chat = client.post("/api/chat", json={"session_id": sid, "message": "done"})
        assert chat.status_code == 200
        assert chat.json()["assessment_status"] == "likely_eligible"
        cites = chat.json()["citations"]
        assert cites
        assert "title" in cites[0]
        assert "url" in cites[0]
        assert "morefood.org" in cites[0]["url"]
        assert "nc-fns-income-limits" not in cites[0]["title"]
        assert all("source_id" not in c for c in cites)


@pytest.mark.usefixtures("fake_session_store")
def test_chat_rejects_empty_message() -> None:
    with TestClient(app) as client:
        sid = client.post("/api/session", json={"program_slug": "nc-fns"}).json()["session_id"]
        bad = client.post("/api/chat", json={"session_id": sid, "message": ""})
        assert bad.status_code == 422


@pytest.mark.usefixtures("fake_session_store")
def test_multi_turn_session_persistence() -> None:
    with (
        patch("src.api.app.process_turn", side_effect=_fake_process),
        TestClient(app) as client,
    ):
        sid = client.post("/api/session", json={"program_slug": "nc-fns"}).json()["session_id"]
        client.post("/api/chat", json={"session_id": sid, "message": "live in NC"})
        client.post("/api/chat", json={"session_id": sid, "message": "second turn"})
        state = client.get(f"/api/session/{sid}/state").json()["state"]
        assert state["lives_in_service_area"]["value"] is True


@pytest.mark.usefixtures("fake_session_store")
def test_root_not_a_web_ui() -> None:
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code in {404, 405, 307, 308}
