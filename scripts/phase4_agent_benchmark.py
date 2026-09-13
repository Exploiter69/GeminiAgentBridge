#!/usr/bin/env python3
"""Live Phase 4 bridge benchmark for 5/10/15/22 synthetic tools."""
from __future__ import annotations
import json, os, time, urllib.error, urllib.request

URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8081/v1/chat/completions")
MODEL = os.getenv("BRIDGE_MODEL", "gemini-3.1-pro")
API_KEY = os.getenv("BRIDGE_API_KEY", "")


def tools(n):
    return [{"type": "function", "function": {"name": f"tool_{i}", "description": f"Inspect local coding target {i}.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}} for i in range(n)]


def run(n):
    target = f"tool_{n - 1}"
    payload = {"model": MODEL, "messages": [{"role": "user", "content": f"Call {target} now for path sample.txt."}], "tools": tools(n), "tool_choice": {"type": "function", "function": {"name": target}}, "stream": False}
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
            status = resp.status
    except urllib.error.HTTPError as exc:
        return {"tools": n, "status": exc.code, "ok": False, "error": f"HTTP {exc.code}", "latency_ms": round((time.monotonic() - started) * 1000)}
    except Exception as exc:
        return {"tools": n, "status": None, "ok": False, "error": type(exc).__name__, "latency_ms": round((time.monotonic() - started) * 1000)}
    choice = ((data.get("choices") or [{}])[0]).get("message") or {}
    calls = choice.get("tool_calls") or []
    names = [((c.get("function") or {}).get("name")) for c in calls]
    return {"tools": n, "status": status, "ok": status == 200 and target in names, "tool_calls": len(calls), "target_seen": target in names, "latency_ms": round((time.monotonic() - started) * 1000)}


def main():
    results = [run(n) for n in (5, 10, 15, 22)]
    print(json.dumps({"model": MODEL, "url": URL, "results": results}, indent=2))
    raise SystemExit(1 if any(not r.get("ok") for r in results) else 0)


if __name__ == "__main__":
    main()
