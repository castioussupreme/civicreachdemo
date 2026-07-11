"""JSON-shaped types without typing.Any (for LLM payloads and summaries)."""

from __future__ import annotations

from typing import TypeAlias

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def as_json_value(value: object) -> JsonValue:
    """Coerce a json.loads result into JsonValue (rejects non-JSON types)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [as_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_json_value(item) for key, item in value.items()}
    raise TypeError(f"unsupported JSON type: {type(value).__name__}")


def as_json_object(value: object) -> JsonObject:
    """Validate that a parsed JSON value is an object."""
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object, got {type(value).__name__}")
    return {str(key): as_json_value(item) for key, item in value.items()}
