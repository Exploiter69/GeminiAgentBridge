"""Safe request lifecycle tracing for GeminiAgentBridge.

The bridge must be observable without becoming a credential logger.  This module
only records identifiers, sizes, timing, status, model names and tool names.
Request bodies, authorization headers, cookies, API keys and session material
are deliberately excluded.
"""
from __future__ import annotations

import time
import uuid
from typing import Iterable


TRACE_HEADER = "X-Bridge-Trace-Id"


def new_trace_id() -> str:
    """Return a short, non-secret request correlation identifier."""
    return uuid.uuid4().hex[:16]


def elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


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


def request_summary(method: str, path: str, trace_id: str, body_size: int = 0) -> dict:
    """Build a safe lifecycle event with no request content."""
    return {
        "event": "request.start",
        "trace_id": trace_id,
        "method": method,
        "path": path.split("?", 1)[0],
        "body_bytes": int(body_size),
    }


def response_summary(
    trace_id: str,
    status: int,
    duration_ms: int,
    model: str | None = None,
    tool_names: Iterable[str] | None = None,
) -> dict:
    """Build a safe response lifecycle event."""
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
