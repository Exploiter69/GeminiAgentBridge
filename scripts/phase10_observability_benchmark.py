#!/usr/bin/env python3
"""Deterministic Phase 10 observability/auditability benchmark."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_web2api.observability import (
    EVENT_NAMES,
    TraceRecorder,
    make_event,
    new_trace_id,
    safe_path,
    safe_tool_names,
)


def main() -> int:
    trace = new_trace_id()
    recorder = TraceRecorder(max_events=128)
    for name in EVENT_NAMES:
        recorder.record(make_event(trace, name, status="ok", tool_names=["read_file"] if "tool" in name else []))

    events = recorder.snapshot(trace)
    payload = json.dumps(events, ensure_ascii=False, sort_keys=True)
    checks = {
        "all_events_present": [e["event"] for e in events] == list(EVENT_NAMES),
        "single_trace": bool(events) and all(e["trace_id"] == trace for e in events),
        "query_redaction": "secret" not in safe_path("/v1/models?key=secret"),
        "tool_argument_exclusion": safe_tool_names([{"function": {"name": "read_file", "arguments": "secret"}}]) == ["read_file"],
        "json_serializable": bool(payload),
    }
    result = {
        "phase": 10,
        "name": "observability",
        "cases": len(checks),
        "passed": sum(checks.values()),
        "failed": sum(not value for value in checks.values()),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
