"""Safe, structured request/trajectory observability.

The bridge must be diagnosable without becoming a credential or content logger.
Events therefore contain correlation IDs, lifecycle names, sizes, timing, status,
model names, tool names and bounded metadata only. Request/response bodies,
tool arguments, authorization headers, cookies, API keys and session material
are never emitted by this module.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import deque
from typing import Any, Iterable

TRACE_HEADER = "X-Bridge-Trace-Id"
_SECRET_KEY_RE = re.compile(
    r"(?:authorization|cookie|set-cookie|api[_-]?key|token|secret|password|session|xsrf|credential)",
    re.I,
)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:key|api[_-]?key|token|access_token|auth|session)=)[^&\s]+",
    re.I,
)

# Roadmap Phase 10 canonical lifecycle names. Keep these stable for log consumers.
EVENT_NAMES = (
    "request_received",
    "context_built",
    "prompt_built",
    "upstream_request",
    "upstream_response",
    "candidate_tool_call",
    "parsed_tool_call",
    "schema_validation",
    "repair_attempt",
    "client_tool_call_returned",
    "observation_received",
    "observation_validated",
    "next_turn",
    "request_completed",
    "request_failed",
)


def new_trace_id() -> str:
    """Return a short, non-secret request correlation identifier."""
    return uuid.uuid4().hex[:16]


def elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def safe_path(value: object) -> str:
    """Remove credentials from URL-like values before they reach logs."""
    return _SECRET_QUERY_RE.sub(r"\1[REDACTED]", str(value))


def safe_tool_names(tool_calls: Iterable[dict] | None) -> list[str]:
    """Extract tool names only; never serialize arguments."""
    names: list[str] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = function.get("name") or call.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _safe_value(key: str, value: Any) -> Any:
    if _SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(key, item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = safe_path(value) if isinstance(value, str) else value
        if isinstance(text, str) and len(text) > 240:
            return f"{text[:120]}…{text[-80:]}"
        return text
    return type(value).__name__


def sanitize_event(fields: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded event with credential-bearing keys/URLs redacted."""
    return {str(k): _safe_value(str(k), v) for k, v in fields.items()}


def make_event(trace_id: str, event: str, **fields: Any) -> dict[str, Any]:
    """Build one canonical JSON-serializable lifecycle event."""
    if event not in EVENT_NAMES:
        raise ValueError(f"unknown observability event: {event}")
    return {
        "ts": time.time(),
        "event": event,
        "trace_id": trace_id,
        **sanitize_event(fields),
    }


class TraceRecorder:
    """Thread-safe bounded event recorder for tests and local diagnostics.

    The recorder keeps only safe structured events. It is intentionally bounded
    so observability cannot become an unbounded memory sink during long runs.
    """

    def __init__(self, max_events: int = 512):
        self._events = deque(maxlen=max(1, int(max_events)))
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        safe = sanitize_event(event)
        with self._lock:
            self._events.append(dict(safe))
        return safe

    def snapshot(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if trace_id is not None:
            items = [item for item in items if item.get("trace_id") == trace_id]
        return items

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_GLOBAL_RECORDER = TraceRecorder()


def emit_event(trace_id: str, event: str, **fields: Any) -> dict[str, Any]:
    """Record and return a safe event for a request lifecycle."""
    return _GLOBAL_RECORDER.record(make_event(trace_id, event, **fields))


def get_trace_events(trace_id: str | None = None) -> list[dict[str, Any]]:
    return _GLOBAL_RECORDER.snapshot(trace_id)


def clear_trace_events() -> None:
    _GLOBAL_RECORDER.clear()


def event_json(event: dict[str, Any]) -> str:
    """Serialize a pre-sanitized event as one deterministic JSON log line."""
    return json.dumps(sanitize_event(event), ensure_ascii=False, sort_keys=True)


def request_summary(method: str, path: str, trace_id: str, body_size: int = 0) -> dict:
    """Backward-compatible safe request lifecycle summary."""
    return {
        "event": "request.start",
        "trace_id": trace_id,
        "method": method,
        "path": safe_path(path).split("?", 1)[0],
        "body_bytes": int(body_size),
    }


def response_summary(
    trace_id: str,
    status: int,
    duration_ms: int,
    model: str | None = None,
    tool_names: Iterable[str] | None = None,
) -> dict:
    """Backward-compatible safe response lifecycle summary."""
    event = {
        "event": "request.end",
        "trace_id": trace_id,
        "status": int(status),
        "duration_ms": int(duration_ms),
    }
    if model:
        event["model"] = model
    if tool_names:
        event["tool_names"] = list(tool_names)
    return event
