"""Response semantic guards for fields unavailable from Gemini Web.

Gemini Web does not expose authoritative OpenAI-compatible token accounting through
this bridge. Estimated character/token counts therefore must never be presented as
provider usage. This module removes fabricated ``usage`` fields while preserving
all other response semantics.
"""
from __future__ import annotations

from typing import Any


def remove_fabricated_usage(value: Any) -> Any:
    """Return a response payload with synthetic token accounting removed.

    This deliberately removes every mapping key named ``usage``. The bridge only
    invokes this for outbound OpenAI/Responses compatibility payloads, never for
    arbitrary upstream data or request bodies.
    """
    if isinstance(value, dict):
        return {
            key: remove_fabricated_usage(item)
            for key, item in value.items()
            if key != "usage"
        }
    if isinstance(value, list):
        return [remove_fabricated_usage(item) for item in value]
    return value


def sanitize_sse_event(data: bytes) -> bytes:
    """Remove fabricated usage from one or more complete SSE events."""
    text = data.decode("utf-8", errors="replace")
    blocks = text.split("\n\n")
    output: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        sanitized: list[str] = []
        for line in lines:
            if not line.startswith("data: "):
                sanitized.append(line)
                continue
            payload = line[6:]
            if payload == "[DONE]":
                sanitized.append(line)
                continue
            try:
                import json
                obj = json.loads(payload)
            except (TypeError, ValueError):
                sanitized.append(line)
            else:
                sanitized.append("data: " + json.dumps(remove_fabricated_usage(obj), ensure_ascii=False, separators=(",", ":")))
        output.append("\n".join(sanitized))
    return "\n\n".join(output).encode("utf-8")
