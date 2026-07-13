from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, cast

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ProgramCatalogItem,
    SessionCreateRequest,
    SessionCreateResponse,
    StateResponse,
)
from src.config import get_settings
from src.openai_errors import OpenAIServiceError
from src.process_turn import process_turn
from src.programs.registry import (
    ProgramNotAvailableError,
    ProgramNotFoundError,
    catalog_programs,
    default_program_slug,
    resolve_ruleset,
)
from src.retrieval.index import ensure_index
from src.retrieval.kb import public_citation_dicts
from src.session import SessionStoreProtocol, open_session_store

logger = logging.getLogger("uvicorn.error")


def _halt_process(code: int, *, reason: str) -> None:
    """
    Force process exit with the given code.

    Do NOT use SystemExit inside the FastAPI/Starlette lifespan: uvicorn treats
    lifespan failures as exit code 3, which makes ``restart: on-failure`` loop.
    os._exit bypasses that and is what Docker actually sees.
    """
    logger.error("%s", reason)
    # Flush logs before hard exit
    for handler in logging.root.handlers:
        handler.flush()
    for handler in logger.handlers:
        handler.flush()
    os._exit(code)


def _endpoints(base: str) -> dict[str, str]:
    b = base.rstrip("/")
    return {
        "health": f"{b}/api/health",
        "openapi": f"{b}/docs",
        "programs": f"{b}/api/programs",
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
        "retrieval": "qdrant+openai-embeddings",
        "qdrant_url": s.public_qdrant_url or s.qdrant_url,
        "embedding_model": s.openai_embedding_model,
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
        f"  Embeddings    {settings.openai_embedding_model}",
        "  Sessions      redis",
        f"  Redis         {settings.public_redis_url}",
        f"  Qdrant        {settings.public_qdrant_url or settings.qdrant_url}",
        "  Retrieval     vector RAG (incremental index)",
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
    # Vector RAG is required at startup. Exit codes + restart: on-failure:
    #   0 = permanent (quota/auth) → stay down (no loop)
    #   1 = transient → Compose may restart
    try:
        result = ensure_index()
    except OpenAIServiceError as exc:
        # Full provider detail for operators (Docker logs); not sent to clients
        logger.error("%s", exc.log_message)
        if exc.raw_detail:
            logger.error("full provider error: %s", exc.raw_detail)
        if exc.kind in {"quota", "auth"}:
            _halt_process(
                0,
                reason=(
                    "Permanent OpenAI billing/config issue — process exit 0 "
                    "(Docker restart: on-failure will NOT restart). "
                    "After fixing quota: make up-d"
                ),
            )
        _halt_process(
            1,
            reason=(
                f"Transient OpenAI error building the knowledge index (kind={exc.kind}) "
                "— process exit 1 (Docker may restart)."
            ),
        )
    except Exception as exc:
        logger.exception("Unexpected failure building knowledge index")
        _halt_process(
            1,
            reason=(
                f"Failed to build knowledge index (embeddings/Qdrant): {exc}. "
                "Process exit 1 (Docker may restart)."
            ),
        )
    if result is not None:
        logger.info(
            "Knowledge RAG index: skipped=%s reembedded=%s orphans=%s chunks=%s",
            result.skipped,
            result.reembedded,
            result.orphans_deleted,
            result.chunks_upserted,
        )
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
    as_of = date.today()
    active = catalog_programs(as_of=as_of, limit=100)
    default_slug = default_program_slug()
    try:
        default_rs = resolve_ruleset(default_slug, as_of)
        ruleset_id = default_rs.id
    except Exception:
        ruleset_id = ""
    return HealthResponse(
        status="ok",
        service="eligibility-agent",
        openai_model=settings.openai_model,
        ruleset_id=ruleset_id,
        default_program=default_slug,
        active_programs=len(active),
        public_base_url=settings.public_base_url,
        endpoints=_endpoints(settings.public_base_url),
        resources=_resources(),
    )


@app.get("/api/programs", response_model=list[ProgramCatalogItem])
def list_programs(
    q: Annotated[str, Query(description="Substring filter on name/slug/aliases")] = "",
    as_of: Annotated[str | None, Query(description="ISO date YYYY-MM-DD")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ProgramCatalogItem]:
    when = date.today()
    if as_of:
        try:
            when = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    entries = catalog_programs(q=q, as_of=when, limit=limit)
    return [
        ProgramCatalogItem(
            slug=e.slug,
            display_name=e.display_name,
            ruleset_id=e.ruleset_id,
            effective_from=e.effective_from,
            effective_to=e.effective_to,
            search_aliases=list(e.search_aliases),
        )
        for e in entries
    ]


@app.post("/api/session", response_model=SessionCreateResponse)
def create_session(
    request: Request,
    body: SessionCreateRequest | None = None,
) -> SessionCreateResponse:
    payload = body or SessionCreateRequest()
    slug = (payload.program_slug or "").strip() or default_program_slug()
    as_of = (payload.as_of or "").strip() or None
    when = date.today()
    if as_of:
        try:
            when = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    try:
        resolve_ruleset(slug, when)
    except ProgramNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgramNotAvailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sid = _get_store(request).create(program_slug=slug, as_of=when.isoformat())
    case = _get_store(request).get(sid)
    opening = case.recent_turns[0].text if case.recent_turns else ""
    return SessionCreateResponse(
        session_id=sid,
        opening_message=opening,
        program_slug=case.program_slug,
        ruleset_id=case.ruleset_id,
        as_of=case.as_of,
        ruleset_effective_from=case.ruleset_effective_from,
        ruleset_effective_to=case.ruleset_effective_to,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(
    request: Request,
    body: ChatRequest,
    debug: Annotated[bool, Query()] = False,
) -> ChatResponse | JSONResponse:
    sessions = _get_store(request)
    session_id = body.session_id or sessions.create()
    case = sessions.get(session_id)
    program_slug = case.program_slug
    try:
        result = process_turn(body.message, case)
    except OpenAIServiceError as exc:
        # Defense in depth — process_turn usually converts these to a friendly reply.
        logger.error("%s", exc.log_message)
        if exc.raw_detail:
            logger.error("full provider error: %s", exc.raw_detail)
        return JSONResponse(
            status_code=503,
            content={
                "detail": exc.user_message,
                "error": "service_unavailable",
                "session_id": session_id,
            },
        )
    sessions.set(session_id, result.case)

    assessment_status = result.assessment.status.value if result.assessment is not None else None
    assessment_payload: dict[str, object] | None = None
    source_ids: list[str] = []
    if result.case.assessment is not None:
        assessment_payload = dict(result.case.assessment.model_dump())
        source_ids = list(result.case.assessment.source_ids)
    # Human title/URL for clients (CLI card); no internal source ids.
    citations_payload = public_citation_dicts(
        result.citations,
        source_ids=source_ids or None,
        limit=4,
        program_slug=program_slug,
    )
    # stage/assessment_status are for clients; reply text stays human-facing.
    # Full plan/extract metadata only when ?debug=true.
    debug_payload: dict[str, object] | None = dict(result.debug) if debug else None
    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        safety_action=result.safety_action,
        stage=result.case.stage.value,
        assessment_status=assessment_status,
        assessment=assessment_payload,
        citations=citations_payload,
        program_slug=result.case.program_slug,
        ruleset_id=result.case.ruleset_id,
        debug=debug_payload,
    )


@app.get("/api/session/{session_id}/state", response_model=StateResponse)
def session_state(request: Request, session_id: str) -> StateResponse:
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    case = _get_store(request).get(session_id)
    assessment_payload: dict[str, object] | None = None
    source_ids: list[str] = []
    if case.assessment is not None:
        assessment_payload = dict(case.assessment.model_dump())
        source_ids = list(case.assessment.source_ids)
    return StateResponse(
        session_id=session_id,
        state=dict(case.known_summary()),
        assessment=assessment_payload,
        citations=public_citation_dicts(
            source_ids=source_ids or None,
            limit=4,
            program_slug=case.program_slug,
        ),
        program_slug=case.program_slug,
        ruleset_id=case.ruleset_id,
    )


@app.post("/api/session/{session_id}/reset", response_model=SessionCreateResponse)
def reset_session(
    request: Request,
    session_id: str,
    body: SessionCreateRequest | None = None,
) -> SessionCreateResponse:
    payload = body or SessionCreateRequest()
    existing = _get_store(request).get(session_id)
    slug = (payload.program_slug or "").strip() or existing.program_slug or default_program_slug()
    as_of = (payload.as_of or "").strip() or existing.as_of or None
    when = date.today()
    if as_of:
        try:
            when = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    try:
        resolve_ruleset(slug, when)
    except ProgramNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgramNotAvailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = _get_store(request).reset(session_id, program_slug=slug, as_of=when.isoformat())
    opening = case.recent_turns[0].text if case.recent_turns else ""
    return SessionCreateResponse(
        session_id=session_id,
        opening_message=opening,
        program_slug=case.program_slug,
        ruleset_id=case.ruleset_id,
        as_of=case.as_of,
        ruleset_effective_from=case.ruleset_effective_from,
        ruleset_effective_to=case.ruleset_effective_to,
    )
