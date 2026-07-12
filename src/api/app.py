from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import FastAPI, HTTPException, Query, Request

from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionCreateResponse,
    StateResponse,
)
from src.config import get_settings
from src.eligibility.ruleset import RULESET
from src.process_turn import process_turn
from src.session import SessionStoreProtocol, open_session_store
from src.state.models import OPENING_MESSAGE

logger = logging.getLogger("uvicorn.error")


def _endpoints(base: str) -> dict[str, str]:
    b = base.rstrip("/")
    return {
        "health": f"{b}/api/health",
        "openapi": f"{b}/docs",
        "create_session": f"{b}/api/session",
        "chat": f"{b}/api/chat",
        "state": f"{b}/api/session/{{session_id}}/state",
        "reset": f"{b}/api/session/{{session_id}}/reset",
    }


def _resources() -> dict[str, str]:
    s = get_settings()
    return {
        "sessions": "redis",
        "redis_url": s.public_redis_url,
        "redis_note": "Dev Redis: no auth. Do not expose publicly.",
    }


def _log_banner() -> None:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    lines = [
        "",
        "═" * 56,
        "  NC FNS Eligibility Agent is up",
        "═" * 56,
        f"  API health    {base}/api/health",
        f"  OpenAPI docs  {base}/docs",
        f"  Chat API      POST {base}/api/chat",
        f"  Model         {settings.openai_model}",
        "  Sessions      redis",
        f"  Redis         {settings.public_redis_url}",
        "  Redis creds   (none — open dev instance)",
        "═" * 56,
        "",
    ]
    for line in lines:
        logger.info(line)


def _get_store(request: Request) -> SessionStoreProtocol:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Session store not ready")
    return cast(SessionStoreProtocol, store)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        settings = get_settings()
    except Exception as exc:
        logger.error("Invalid configuration: %s", exc)
        raise

    app.state.store = open_session_store(settings.effective_redis_url())
    _log_banner()
    yield


app = FastAPI(
    title="NC FNS Eligibility Agent",
    description="Informal NC FNS / SNAP screening POC — not an official determination.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="nc-fns-eligibility-agent",
        openai_model=settings.openai_model,
        ruleset_id=RULESET.id,
        public_base_url=settings.public_base_url,
        endpoints=_endpoints(settings.public_base_url),
        resources=_resources(),
    )


@app.post("/api/session", response_model=SessionCreateResponse)
def create_session(request: Request) -> SessionCreateResponse:
    sid = _get_store(request).create()
    case = _get_store(request).get(sid)
    opening = case.recent_turns[0].text if case.recent_turns else OPENING_MESSAGE
    return SessionCreateResponse(session_id=sid, opening_message=opening)


@app.post("/api/chat", response_model=ChatResponse)
def chat(
    request: Request,
    body: ChatRequest,
    debug: Annotated[bool, Query()] = False,
) -> ChatResponse:
    sessions = _get_store(request)
    session_id = body.session_id or sessions.create()
    case = sessions.get(session_id)
    result = process_turn(body.message, case)
    sessions.set(session_id, result.case)

    assessment_status = result.assessment.status.value if result.assessment is not None else None
    # stage/assessment_status are for clients; reply text stays human-facing.
    # Full plan/extract metadata only when ?debug=true.
    debug_payload: dict[str, object] | None = dict(result.debug) if debug else None
    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        safety_action=result.safety_action,
        stage=result.case.stage.value,
        assessment_status=assessment_status,
        debug=debug_payload,
    )


@app.get("/api/session/{session_id}/state", response_model=StateResponse)
def session_state(request: Request, session_id: str) -> StateResponse:
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    case = _get_store(request).get(session_id)
    return StateResponse(session_id=session_id, state=dict(case.known_summary()))


@app.post("/api/session/{session_id}/reset", response_model=SessionCreateResponse)
def reset_session(request: Request, session_id: str) -> SessionCreateResponse:
    case = _get_store(request).reset(session_id)
    opening = case.recent_turns[0].text if case.recent_turns else OPENING_MESSAGE
    return SessionCreateResponse(session_id=session_id, opening_message=opening)
