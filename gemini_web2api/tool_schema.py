"""Deterministic, semantics-preserving tool-schema normalization."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .config import CONFIG

_COSMETIC_KEYS = {"title", "$schema", "$id", "examples"}
# Keywords that can change whether an agent-generated argument is accepted must
# survive compaction. Defaults are also retained because downstream tool
# executors may rely on them even when the model omits the field.
_SEMANTIC_KEYS = {
    "type", "description", "properties", "required", "items", "enum",
    "additionalProperties", "anyOf", "oneOf", "allOf", "const", "pattern",
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minItems", "maxItems", "uniqueItems", "default",
    "format", "nullable", "prefixItems", "contains", "minProperties",
    "maxProperties", "dependentRequired", "dependentSchemas", "not",
}


def _shorten(text: Any, limit: int) -> Any:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _normalize_schema(schema: Any, description_limit: int = 220) -> Any:
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _COSMETIC_KEYS:
            continue
        if key == "description":
            out[key] = _shorten(value, description_limit)
        elif key == "properties" and isinstance(value, dict):
            out[key] = {str(name): _normalize_schema(item, description_limit) for name, item in value.items()}
        elif key in {"items", "additionalProperties", "not", "contains"}:
            out[key] = _normalize_schema(value, description_limit)
        elif key in {"anyOf", "oneOf", "allOf", "prefixItems"} and isinstance(value, list):
            out[key] = [_normalize_schema(item, description_limit) for item in value]
        elif key in _SEMANTIC_KEYS:
            out[key] = deepcopy(value)
        else:
            # Unknown extension keywords are retained rather than silently
            # deleting provider-specific semantics.
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


def _drop_cosmetic_metadata(node: Any, description_limit: int = 110) -> Any:
    if isinstance(node, list):
        return [_drop_cosmetic_metadata(x, description_limit) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in _COSMETIC_KEYS:
            continue
        if key == "description":
            out[key] = _shorten(value, description_limit)
        elif key == "properties" and isinstance(value, dict):
            out[key] = {k: _drop_cosmetic_metadata(v, description_limit) for k, v in value.items()}
        else:
            out[key] = _drop_cosmetic_metadata(value, description_limit)
    return out


def normalize_tool_definitions(tools: list[dict[str, Any]] | None, max_chars: int | None = None) -> list[dict[str, Any]]:
    """Compact schemas without deleting callable tools or semantic constraints.

    If the requested budget is too small to represent a tool faithfully, the
    tool is retained and only descriptive/cosmetic text is shortened. The
    function never removes required/default/enum/type constraints merely to hit
    a character budget.
    """
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
        tool["parameters"] = _drop_cosmetic_metadata(tool["parameters"], 110)
    if len(_serialized(reduced)) <= budget:
        return reduced

    # A hard budget cannot justify semantic deletion. Return the reduced
    # representation even if it exceeds the advisory budget; callers can then
    # explicitly decide whether to reject the request or use a larger context.
    return reduced


def tool_schema_size(tools: list[dict[str, Any]]) -> int:
    return len(_serialized(tools))
