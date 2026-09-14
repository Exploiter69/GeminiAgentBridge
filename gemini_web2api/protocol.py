"""Robust tool-call protocol helpers for agent runtimes."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from typing import Any

_SENTINEL_RE = re.compile(r"@@TOOL_CALL@@\s*(?P<body>.*?)\s*@@END_TOOL_CALL@@", re.DOTALL)
_FENCED_RE = re.compile(r"```tool_call\s*(?:\n)?(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE)

STRICT_TOOL_PROTOCOL = (
    "# Strict Tool Use Protocol\n\n"
    "When you need to call a tool, output ONLY the following exact block; do not use Markdown fences:\n"
    "@@TOOL_CALL@@\n"
    '{"name":"tool_name","arguments":{...}}\n'
    "@@END_TOOL_CALL@@\n\n"
    "Rules:\n"
    "- Use exactly the tool name from Available tools.\n"
    "- arguments MUST be a JSON object.\n"
    "- Output valid JSON only inside the block.\n"
    "- Do not put tool calls in normal prose.\n"
    "- Do not repeat a tool call that has already been completed unless its arguments must genuinely be retried.\n"
    "- You may emit multiple blocks when multiple independent tool calls are needed.\n"
)

_REPAIR_PREFIX = (
    "# Tool Call Repair\n\n"
    "Your previous response contained an invalid tool call. Correct it and retry.\n"
    "Do not invent a new task or tool intent. Preserve the user's original request.\n"
    "Output ONLY the corrected @@TOOL_CALL@@ block(s), with no Markdown fences or prose.\n"
)

_tool_context = threading.local()


def set_tool_context(tool_defs: list[dict[str, Any]] | None, tool_choice: Any = "auto") -> None:
    _tool_context.tool_defs = tool_defs or []
    _tool_context.tool_choice = tool_choice


def get_tool_context() -> tuple[list[dict[str, Any]], Any]:
    return getattr(_tool_context, "tool_defs", []), getattr(_tool_context, "tool_choice", "auto")


def clear_tool_context() -> None:
    for attr in ("tool_defs", "tool_choice"):
        if hasattr(_tool_context, attr):
            delattr(_tool_context, attr)


def _balanced_json_objects(text: str) -> list[tuple[int, int, str]]:
    """Find balanced JSON objects while respecting quoted strings/escapes."""
    found = []
    for start in (m.start() for m in re.finditer(r"\{", text)):
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    found.append((start, index + 1, text[start:index + 1]))
                    break
    return found


def _candidate_objects(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in (_SENTINEL_RE, _FENCED_RE):
        for match in pattern.finditer(text):
            found.append((match.start(), match.end(), match.group("body")))
            occupied.append((match.start(), match.end()))
    for start, end, body in _balanced_json_objects(text):
        # Raw JSON is only considered a tool candidate if it looks like one;
        # this avoids deleting ordinary JSON answers from assistant content.
        if '"name"' not in body or ('"arguments"' not in body and '"args"' not in body):
            continue
        if any(a <= start < b for a, b in occupied):
            continue
        found.append((start, end, body))
    found.sort(key=lambda item: item[0])
    return found


def _decode_object(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def _normalize(obj: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    arguments = obj.get("arguments", obj.get("args", {}))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return None
    return name.strip(), arguments


def parse_tool_calls_robust(text: str) -> tuple[str, list[dict[str, Any]]]:
    if not text:
        return text or "", []
    calls: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    seen: set[str] = set()
    for start, end, raw in _candidate_objects(text):
        obj = _decode_object(raw)
        if obj is None:
            continue
        normalized = _normalize(obj)
        if normalized is None:
            continue
        name, arguments = normalized
        canonical = json.dumps({"name": name, "arguments": arguments}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        spans.append((start, end))
        if canonical in seen:
            continue
        seen.add(canonical)
        digest = hashlib.sha256(f"{len(calls)}:{canonical}".encode()).hexdigest()[:12]
        calls.append({"id": f"call_{digest}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))}})
    if not spans:
        return text.strip(), calls
    clean = text
    for start, end in sorted(spans, reverse=True):
        clean = clean[:start] + clean[end:]
    return clean.strip(), calls


def _schema_type_ok(value: Any, schema_type: str) -> bool:
    return {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool), "number": isinstance(value, (int, float)) and not isinstance(value, bool), "boolean": isinstance(value, bool), "null": value is None}.get(schema_type, True)


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and not _schema_type_ok(value, schema_type):
        return [f"{path}: expected {schema_type}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not allowed")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required field is missing")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, item in value.items():
                if key in properties:
                    errors.extend(_validate_value(item, properties[key], f"{path}.{key}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{key}: unexpected field")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(_validate_value(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, str) and isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
        errors.append(f"{path}: string is too short")
    return errors


def _tool_def_map(tool_defs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for tool in tool_defs or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(fn.get("name"), str) and fn["name"]:
            result[fn["name"]] = fn
    return result


def validate_tool_calls(tool_calls: list[dict[str, Any]], tool_defs: list[dict[str, Any]] | None = None) -> list[str]:
    defs = _tool_def_map(tool_defs or [])
    errors: list[str] = []
    for index, call in enumerate(tool_calls):
        fn = call.get("function", {})
        name = fn.get("name")
        if name not in defs:
            errors.append(f"tool_calls[{index}]: unknown tool '{name}'")
            continue
        try:
            arguments = json.loads(fn.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError):
            errors.append(f"tool_calls[{index}].arguments: invalid JSON")
            continue
        if not isinstance(arguments, dict):
            errors.append(f"tool_calls[{index}].arguments: expected object")
            continue
        errors.extend(_validate_value(arguments, defs[name].get("parameters", {}) or {}, f"tool_calls[{index}].arguments"))
    return errors


def tool_choice_name(tool_choice: Any) -> str | None:
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn = tool_choice.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"].strip():
            return fn["name"].strip()
    return None


def validate_tool_choice(tool_choice: Any, tool_defs: list[dict[str, Any]] | None = None) -> list[str]:
    if tool_choice in (None, "auto", "none", "required"):
        if tool_choice == "required" and not tool_defs:
            return ["tool_choice=required cannot be satisfied without tools"]
        return []
    if not isinstance(tool_choice, dict) or tool_choice.get("type") != "function":
        return ["tool_choice must be one of auto, none, required, or a function choice"]
    name = tool_choice_name(tool_choice)
    if not name:
        return ["tool_choice function name is missing"]
    if name not in _tool_def_map(tool_defs or []):
        return [f"tool_choice requested unknown tool '{name}'"]
    return []


def _attempted_tool_marker(text: str) -> bool:
    return any(marker in (text or "") for marker in ("@@TOOL_CALL@@", "```tool_call", "\ntool_call\n"))


def response_needs_repair(text: str, tool_calls: list[dict[str, Any]], tool_defs: list[dict[str, Any]], tool_choice: Any = "auto") -> bool:
    attempted = _attempted_tool_marker(text)
    validation_errors = validate_tool_calls(tool_calls, tool_defs)
    if tool_choice == "none":
        return attempted or bool(tool_calls)
    requested = tool_choice_name(tool_choice)
    if requested:
        if not tool_calls:
            return True
        if any(call.get("function", {}).get("name") != requested for call in tool_calls):
            return True
    return (attempted and not tool_calls) or bool(validation_errors) or (tool_choice == "required" and not tool_calls)


def build_repair_prompt(original_prompt: str, errors: list[str], tool_choice: Any = "auto", tool_defs: list[dict[str, Any]] | None = None) -> str:
    details = "\n".join(f"- {error}" for error in errors[:8]) or "- tool call was not parseable"
    if tool_choice == "none":
        constraint = "\nTool-choice constraint: NONE. Do not emit any tool call. Return text only.\n"
    elif tool_choice == "required":
        constraint = "\nTool-choice constraint: REQUIRED. Produce a tool call supported by the user's request and the declared tools.\n"
    elif tool_choice_name(tool_choice):
        constraint = f"\nTool-choice constraint: use ONLY the explicitly requested tool '{tool_choice_name(tool_choice)}'. Do not substitute another tool.\n"
    else:
        constraint = ""
    return f"{original_prompt}\n\n{_REPAIR_PREFIX}{constraint}{details}\n"
