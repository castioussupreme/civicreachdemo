from __future__ import annotations

import json

from openai import OpenAI, OpenAIError

from src.config import get_settings
from src.json_types import JsonObject, as_json_object
from src.openai_errors import log_service_error, map_openai_error


def chat_json(
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
) -> JsonObject:
    """Call LLM and parse a JSON object response."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except OpenAIError as exc:
        mapped = map_openai_error(exc, purpose="chat")
        log_service_error(mapped, where="chat_json")
        raise mapped from exc
    content = resp.choices[0].message.content or "{}"
    return as_json_object(json.loads(content))


def chat_text(
    *,
    system: str,
    user: str,
    temperature: float = 0.3,
) -> str:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except OpenAIError as exc:
        mapped = map_openai_error(exc, purpose="chat")
        log_service_error(mapped, where="chat_text")
        raise mapped from exc
    return (resp.choices[0].message.content or "").strip()
