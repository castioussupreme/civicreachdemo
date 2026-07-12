from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import AfterValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "knowledge"

load_dotenv(ROOT / ".env")
# Prefer runtime ports/URLs written by make dev / start.py when present.
load_dotenv(ROOT / ".env.runtime", override=True)


def _require_openai_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("OPENAI_API_KEY is required. Set it in the environment or .env file.")
    return cleaned


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: Annotated[str, AfterValidator(_require_openai_key)]
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Host-facing URLs (logs / /api/health / host CLI).
    public_base_url: str = "http://localhost:0"
    public_redis_url: str = Field(default="", validation_alias="PUBLIC_REDIS_URL")

    # Redis client URL for this process.
    # - Agent container (embedded Redis): redis://redis:6379/0  (Compose DNS)
    # - Host CLI: ignore that and use public_redis_url (e.g. redis://localhost:16379/0)
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    def effective_redis_url(self) -> str:
        """
        Resolve a Redis URL that works for *this* process.

        Inside Docker: prefer REDIS_URL (service name ``redis``).
        On the host (CLI): prefer PUBLIC_REDIS_URL (localhost + published port).
        """
        redis_url = self.redis_url.strip()
        public = self.public_redis_url.strip()

        if _running_in_docker():
            url = redis_url or public
        else:
            # Host: never use Compose-internal hostnames (e.g. redis://redis:6379/0)
            if public:
                url = public
            elif redis_url and _hostname(redis_url) not in {"redis"}:
                url = redis_url
            else:
                url = ""

        if not url:
            raise ValueError(
                "No host-reachable Redis URL. Run `make dev` (or `make up`) first, "
                "then retry `make cli`. Or set PUBLIC_REDIS_URL / REDIS_URL in .env."
            )
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
