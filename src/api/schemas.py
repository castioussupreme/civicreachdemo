from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    openai_model: str
    ruleset_id: str
    public_base_url: str
    endpoints: dict[str, str]
    resources: dict[str, str]


class SessionCreateResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    safety_action: str
    stage: str
    assessment_status: str | None = None
    debug: dict[str, object] | None = None


class StateResponse(BaseModel):
    session_id: str
    state: dict[str, object]
