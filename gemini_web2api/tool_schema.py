"""Deterministic tool-schema normalization for large agent toolsets."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .config import CONFIG

_COSMETIC_KEYS = {"title", "$schema", "$id", "examples"}
_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "additionalProperties", "anyOf", "oneOf", "allOf", "const", "pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}


def _shorten(text: Any, limit: int) -> Any:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _normalize_schema(schema: Any, description_limit: int = 220) -> Any:
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _COSMETIC_KEYS or key == "default":
            continue
        if key == "description":
            out[key] = _shorten(value, description_limit)
        elif key == "properties" and isinstance(value, dict):
            out[key] = {str(name): _normalize_schema(item, description_limit) for name, item in value.items()}
        elif key in {"items", "additionalProperties"}:
            out[key] = _normalize_schema(value, description_limit)
        elif key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list):
            out[key] = [_normalize_schema(item, description_limit) for item in value]
        else:
            out[key] = deepcopy(value)
    return out


def _canonical_tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    fn = tool.get("function", tool) if tool.get("type") == "function" else tool
    if not isinstance(fn, dict):
        return None
    name = fn.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return {
        "name": name.strip(),
        "description": _shorten(fn.get("description", ""), 320),
        "parameters": _normalize_schema(fn.get("parameters") or {"type": "object", "properties": {}}, 220),
    }


def _serialized(tools: list[dict[str, Any]]) -> str:
    return json.dumps(tools, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def normalize_tool_definitions(tools: list[dict[str, Any]] | None, max_chars: int | None = None) -> list[dict[str, Any]]:
    """Compact tool schemas without deleting callable arguments or tools."""
    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools or []:
        item = _canonical_tool(tool)
        if item and item["name"] not in seen:
            canonical.append(item)
            seen.add(item["name"])

    budget = max_chars or int(CONFIG.get("tool_schema_budget_chars", 30000))
    if budget <= 0 or len(_serialized(canonical)) <= budget:
        return canonical

    reduced = deepcopy(canonical)
    for tool in reduced:
        tool["description"] = _shorten(tool.get("description", ""), 160)

        def trim_nested(node: Any) -> Any:
            if isinstance(node, list):
                return [trim_nested(x) for x in node]
            if not isinstance(node, dict):
                return node
            out = {}
            for key, value in node.items():
                if key == "description":
                    out[key] = _shorten(value, 110)
                elif key in {"title", "$schema", "$id", "examples", "default"}:
                    continue
                elif key == "properties" and isinstance(value, dict):
                    out[key] = {k: trim_nested(v) for k, v in value.items()}
                else:
                    out[key] = trim_nested(value)
            return out

        tool["parameters"] = trim_nested(tool["parameters"])

    if len(_serialized(reduced)) <= budget:
        return reduced

    final: list[dict[str, Any]] = []
    for tool in reduced:
        params = tool.get("parameters") or {}
        if isinstance(params, dict):
            params = {k: v for k, v in params.items() if k in _SCHEMA_KEYS}
        final.append({"name": tool["name"], "description": _shorten(tool.get("description", ""), 80), "parameters": params})
    return final


def tool_schema_size(tools: list[dict[str, Any]]) -> int:
    return len(_serialized(tools))
