from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import AfterValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.limits import DEFAULT_MAX_MESSAGE_CHARS, HARD_MAX_MESSAGE_CHARS

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS_DIR = ROOT / "programs"

load_dotenv(ROOT / ".env")
# Prefer runtime ports/URLs written by make dev / start.py when present.
load_dotenv(ROOT / ".env.runtime", override=True)


def resolve_public_api_base() -> str:
    """
    Host-facing API base URL for CLI/smoke clients.

    Does not require OPENAI_API_KEY — the agent container holds credentials.
    Reads PUBLIC_BASE_URL from the environment / .env.runtime after load_dotenv.
    """
    # Re-read runtime file so a freshly started stack is visible without process restart
    load_dotenv(ROOT / ".env.runtime", override=True)
    url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not url or url.endswith(":0") or "://localhost:0" in url or "://127.0.0.1:0" in url:
        raise ValueError(
            "API base URL is not set. Start the stack first (make up-d / make dev), "
            "which writes PUBLIC_BASE_URL to .env.runtime."
        )
    return url


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
    # Same OpenAI account as chat — used for knowledge embeddings (RAG).
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )

    # Host-facing URLs (logs / /api/health / host CLI).
    public_base_url: str = "http://localhost:0"
    public_redis_url: str = Field(default="", validation_alias="PUBLIC_REDIS_URL")
    public_qdrant_url: str = Field(default="", validation_alias="PUBLIC_QDRANT_URL")

    # Redis client URL for this process.
    # - Agent container (embedded Redis): redis://redis:6379/0  (Compose DNS)
    # - Host CLI: ignore that and use public_redis_url (e.g. redis://localhost:16379/0)
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    # Qdrant client URL for this process (vector RAG index).
    # - Agent container: http://qdrant:6333
    # - Host CLI: http://localhost:{QDRANT_PORT}
    qdrant_url: str = Field(default="", validation_alias="QDRANT_URL")

    # Same limit for accepted user input and transcript retention (override via env).
    max_message_chars: int = Field(
        default=DEFAULT_MAX_MESSAGE_CHARS,
        ge=100,
        le=HARD_MAX_MESSAGE_CHARS,
        validation_alias="MAX_MESSAGE_CHARS",
    )
    retrieval_top_k: int = Field(default=3, ge=1, le=20)

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

    def effective_qdrant_url(self) -> str:
        """
        Resolve a Qdrant URL that works for *this* process.

        Inside Docker: prefer QDRANT_URL (service name ``qdrant``).
        On the host: prefer PUBLIC_QDRANT_URL (localhost + published port).
        """
        qdrant_url = self.qdrant_url.strip()
        public = self.public_qdrant_url.strip()

        if _running_in_docker():
            url = qdrant_url or public
        else:
            if public:
                url = public
            elif qdrant_url and _hostname(qdrant_url) not in {"qdrant"}:
                url = qdrant_url
            else:
                url = ""

        if not url:
            raise ValueError(
                "No host-reachable Qdrant URL. Run `make dev` (or `make up`) first, "
                "then retry. Or set PUBLIC_QDRANT_URL / QDRANT_URL in .env."
            )
        return url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
