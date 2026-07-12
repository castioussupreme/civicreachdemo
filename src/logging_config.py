"""Logging setup for CLI / smoke (quiet user shell) vs service defaults."""

from __future__ import annotations

import logging


def configure_client_logging(*, verbose: bool = False) -> None:
    """
    Host CLI and smoke: keep the terminal clean.

    - User-facing text is printed by CLI/smoke only.
    - Technical OpenAI/API noise stays at DEBUG (hidden unless verbose).
    - WARNING/ERROR from libraries are suppressed for a quiet shell; the
      Docker agent service still uses uvicorn's default logging.
    """
    level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    # Never dump raw OpenAI SDK payloads to the interactive shell
    for name in (
        "src.llm",
        "src.llm.client",
        "src.retrieval.embeddings",
        "src.retrieval.index",
        "src.retrieval.retrieve",
        "src.openai_errors",
        "openai",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.CRITICAL)
