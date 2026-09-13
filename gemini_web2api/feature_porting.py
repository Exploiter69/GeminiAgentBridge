"""Small, conservative feature ports selected by the Phase 11 roadmap.

This module only normalizes unambiguous enum spelling differences. It never
fuzzily guesses values, changes non-enum arguments, or executes tools.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def _enum_match(value: Any, enum: list[Any]) -> tuple[Any, bool]:
    if value in enum:
        return value, False
    if not isinstance(value, str):
        return value, False

    stripped = value.strip()
    string_matches = [
        candidate
        for candidate in enum
        if isinstance(candidate, str) and candidate.casefold() == stripped.casefold()
    ]
    if len(string_matches) == 1:
        return string_matches[0], True
    return value, False


def _coerce(value: Any, schema: Any) -> tuple[Any, bool]:
    if not isinstance(schema, dict):
        return value, False

    enum = schema.get("enum")
    if isinstance(enum, list):
        value, changed = _enum_match(value, enum)
        if changed:
            return value, True

    changed = False
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        result = dict(value)
        for key, child_schema in schema["properties"].items():
            if key in result:
                result[key], child_changed = _coerce(result[key], child_schema)
                changed = changed or child_changed
        return result, changed

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        result = []
        for item in value:
            coerced, item_changed = _coerce(item, schema["items"])
            result.append(coerced)
            changed = changed or item_changed
        return result, changed

    return value, False


def coerce_tool_call_enums(
    tool_calls: list[dict[str, Any]],
    tool_defs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return normalized calls plus a deterministic list of changed fields.

    Only case/whitespace differences for string enum values are coerced. A
    value is changed only when exactly one enum member matches case-insensitively.
    Unknown tools, malformed JSON, non-enum values, and ambiguous enums are left
    untouched for normal schema validation/repair.
    """
    defs: dict[str, dict[str, Any]] = {}
    for tool in tool_defs or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            defs[fn["name"]] = fn

    normalized = deepcopy(tool_calls)
    changes: list[str] = []
    for index, call in enumerate(normalized):
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        name = fn.get("name") if isinstance(fn, dict) else None
        definition = defs.get(name)
        if not definition:
            continue
        try:
            arguments = json.loads(fn.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(arguments, dict):
            continue
        schema = definition.get("parameters") or {}
        coerced, changed = _coerce(arguments, schema)
        if changed:
            fn["arguments"] = json.dumps(coerced, ensure_ascii=False, separators=(",", ":"))
            changes.append(f"tool_calls[{index}].arguments")
    return normalized, changes


def apply_enum_coercion_in_place(
    tool_calls: list[dict[str, Any]],
    tool_defs: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Apply the conservative normalization in-place for runtime integration."""
    normalized, changes = coerce_tool_call_enums(tool_calls, tool_defs)
    tool_calls[:] = normalized
    return changes
