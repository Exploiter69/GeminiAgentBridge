"""Robust tool-call protocol helpers for agent runtimes.

Gemini Web does not expose native OpenAI tool calls, so the bridge uses a
small textual protocol. This module deliberately accepts the legacy fenced
format as well as the stricter sentinel format, while producing normalized
OpenAI-style tool calls with deterministic IDs.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_SENTINEL_RE = re.compile(
    r"@@TOOL_CALL@@\s*(?P<body>.*?)\s*@@END_TOOL_CALL@@",
    re.DOTALL,
)
_FENCED_RE = re.compile(
    r"```tool_call\s*(?:\n)?(?P<body>.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)
_RAW_FUNCTION_RE = re.compile(
    r"(?:^|\n)tool_call\s*(?:\n)?(?P<body>\{.*?\})",
    re.DOTALL,
)


def _candidate_objects(text: str) -> list[tuple[int, str]]:
    """Return protocol candidates in source order."""
    found: list[tuple[int, str]] = []
    for pattern in (_SENTINEL_RE, _FENCED_RE, _RAW_FUNCTION_RE):
        for match in pattern.finditer(text):
            found.append((match.start(), match.group("body")))
    found.sort(key=lambda item: item[0])
    return found


def _decode_object(raw: str) -> dict[str, Any] | None:
    """Decode one candidate, tolerating harmless surrounding whitespace."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap a JSON object in prose. Extract the outermost
        # object without attempting unsafe or lossy quote substitution.
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def _normalize(obj: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Normalize legacy arguments/args forms and reject malformed calls."""
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
    """Parse tool calls and return clean assistant text plus OpenAI calls.

    The parser is intentionally fail-closed: malformed candidates remain in
    the assistant text instead of being silently turned into an invalid tool
    invocation. Duplicate calls in one model response are removed from the
    visible text while only the first occurrence is emitted as a tool call.
    """
    if not text:
        return text or "", []

    calls: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    seen: set[str] = set()

    for start, raw in _candidate_objects(text):
        obj = _decode_object(raw)
        if obj is None:
            continue
        normalized = _normalize(obj)
        if normalized is None:
            continue
        name, arguments = normalized
        canonical = json.dumps(
            {"name": name, "arguments": arguments},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        # Every valid protocol block is removed from visible assistant text,
        # including duplicates. Only the first occurrence is emitted.
        removed = False
        for pattern in (_SENTINEL_RE, _FENCED_RE, _RAW_FUNCTION_RE):
            for match in pattern.finditer(text):
                if match.start() == start:
                    spans.append((match.start(), match.end()))
                    removed = True
                    break
            if removed:
                break

        if canonical in seen:
            continue
        seen.add(canonical)

        digest = hashlib.sha256(
            f"{len(calls)}:{canonical}".encode("utf-8")
        ).hexdigest()[:12]
        calls.append(
            {
                "id": f"call_{digest}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            }
        )

    if not spans:
        return text.strip(), calls

    clean = text
    for start, end in sorted(spans, reverse=True):
        clean = clean[:start] + clean[end:]
    return clean.strip(), calls
