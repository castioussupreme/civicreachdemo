"""JSON helpers used by case summaries (no LLM)."""

from __future__ import annotations

import pytest
from src.json_types import as_json_object, as_json_value


def test_as_json_value_primitives_and_nested() -> None:
    assert as_json_value(None) is None
    assert as_json_value(True) is True
    assert as_json_value(3) == 3
    assert as_json_value(1.5) == 1.5
    assert as_json_value("x") == "x"
    assert as_json_value([1, {"a": False}]) == [1, {"a": False}]


def test_as_json_value_rejects_unsupported() -> None:
    with pytest.raises(TypeError, match="unsupported JSON"):
        as_json_value({1, 2})  # type: ignore[arg-type]


def test_as_json_object() -> None:
    assert as_json_object({"k": 1}) == {"k": 1}
    with pytest.raises(TypeError, match="JSON object"):
        as_json_object([1, 2])
