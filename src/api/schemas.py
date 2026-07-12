from __future__ import annotations

from pydantic import BaseModel, Field

from src.limits import HARD_MAX_MESSAGE_CHARS


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
    # First assistant line so clients can show it without an empty first turn
    opening_message: str


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
    # Full assessment for clients (e.g. CLI /why card); null while still collecting
    assessment: dict[str, object] | None = None
    debug: dict[str, object] | None = None


class StateResponse(BaseModel):
    session_id: str
    state: dict[str, object]
    assessment: dict[str, object] | None = None
