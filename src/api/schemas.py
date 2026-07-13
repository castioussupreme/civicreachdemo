from __future__ import annotations

from pydantic import BaseModel, Field

from src.limits import HARD_MAX_MESSAGE_CHARS


class HealthResponse(BaseModel):
    status: str
    service: str
    openai_model: str
    ruleset_id: str
    default_program: str
    active_programs: int
    public_base_url: str
    endpoints: dict[str, str]
    resources: dict[str, str]


class ProgramCatalogItem(BaseModel):
    slug: str
    display_name: str
    ruleset_id: str
    effective_from: str
    effective_to: str | None = None
    search_aliases: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    program_slug: str | None = None
    as_of: str | None = None  # ISO date YYYY-MM-DD


class SessionCreateResponse(BaseModel):
    session_id: str
    opening_message: str
    program_slug: str
    ruleset_id: str
    as_of: str
    ruleset_effective_from: str | None = None
    ruleset_effective_to: str | None = None


class ChatRequest(BaseModel):
    # Hard ceiling only; friendly oversize handling uses Settings.max_message_chars.
    message: str = Field(min_length=1, max_length=HARD_MAX_MESSAGE_CHARS)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    safety_action: str
    stage: str
    assessment_status: str | None = None
    assessment: dict[str, object] | None = None
    citations: list[dict[str, str]] = Field(default_factory=list)
    program_slug: str | None = None
    ruleset_id: str | None = None
    debug: dict[str, object] | None = None


class StateResponse(BaseModel):
    session_id: str
    state: dict[str, object]
    assessment: dict[str, object] | None = None
    citations: list[dict[str, str]] = Field(default_factory=list)
    program_slug: str | None = None
    ruleset_id: str | None = None
