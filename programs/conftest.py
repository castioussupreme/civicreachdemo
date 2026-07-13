"""Shared env for pack-local tests (programs/*/tests)."""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
