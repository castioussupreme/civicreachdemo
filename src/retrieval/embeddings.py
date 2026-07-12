"""OpenAI embeddings (same API key as chat)."""

from __future__ import annotations

from openai import OpenAI, OpenAIError

from src.config import get_settings
from src.openai_errors import log_service_error, map_openai_error

# text-embedding-3-small default dimension
EMBEDDING_DIM = 1536


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed one or more strings; returns one vector per input (same order)."""
    if not texts:
        return []
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    vectors: list[list[float]] = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            resp = client.embeddings.create(
                model=settings.openai_embedding_model,
                input=batch,
            )
        except OpenAIError as exc:
            mapped = map_openai_error(exc, purpose="embeddings")
            log_service_error(mapped, where="embeddings.create")
            raise mapped from exc
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([list(item.embedding) for item in ordered])
    return vectors


def embed_query(text: str) -> list[float]:
    vecs = embed_texts([text])
    return vecs[0] if vecs else []
