from __future__ import annotations

import json

from openai import OpenAI

from src.config import get_settings
from src.json_types import JsonObject, as_json_object


def chat_json(
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
) -> JsonObject:
    """Call LLM and parse a JSON object response."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
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
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
