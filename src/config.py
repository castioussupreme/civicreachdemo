from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from pydantic import AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "knowledge"

load_dotenv(ROOT / ".env")


def _require_openai_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("OPENAI_API_KEY is required. Set it in the environment or .env file.")
    return cleaned


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: Annotated[str, AfterValidator(_require_openai_key)]
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Runtime / hosting (host ports are chosen by ./start when not set)
    public_base_url: str = "http://localhost:0"
    session_backend: str = "memory"  # memory | redis
    redis_url: str = "redis://localhost:6379/0"
    public_redis_url: str = "redis://localhost:0/0"


@lru_cache
def get_settings() -> Settings:
    # Fields load from environment / .env (openai_api_key required).
    return Settings()
