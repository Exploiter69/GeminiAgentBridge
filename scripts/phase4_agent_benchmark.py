#!/usr/bin/env python3
"""Live Phase 4 bridge benchmark for 5/10/15/22 synthetic tools."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


URL = os.getenv(
    "BRIDGE_URL",
    "http://127.0.0.1:8081/v1/chat/completions",
)
MODEL = os.getenv("BRIDGE_MODEL", "gemini-3.1-pro")


def load_local_api_key() -> str:
    """Load one configured local bridge key without exposing it."""
    explicit = os.getenv("BRIDGE_API_KEY")
    if explicit:
        return explicit

    config_candidates = [
        os.getenv("BRIDGE_CONFIG"),
        str(Path(__file__).resolve().parents[1] / "config.json"),
        str(Path.home() / ".config/gemini-web2api/config.json"),
    ]

    config_path = next(
        (Path(p) for p in config_candidates if p and Path(p).is_file()),
        None,
    )

    if config_path is None:
        return ""

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""

    keys = config.get("api_keys") or []
    if isinstance(keys, list):
        for key in keys:
            if isinstance(key, str) and key:
                return key

    return ""


API_KEY = os.getenv("BRIDGE_API_KEY") or os.getenv("GEMINI_WEB_API_KEY") or load_local_api_key()


def tools(n: int) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": f"tool_{i}",
                "description": f"Inspect local coding target {i}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }
        for i in range(n)
    ]


def run(n: int) -> dict:
    target = f"tool_{n - 1}"

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"Call {target} now for path sample.txt.",
            }
        ],
        "tools": tools(n),
        "tool_choice": {
            "type": "function",
            "function": {"name": target},
        },
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}

    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    if not API_KEY:
        return {
            "tools": n,
            "status": None,
            "ok": False,
            "error": "AUTH_NOT_CONFIGURED",
            "latency_ms": 0,
        }

    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )

    started = time.monotonic()

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
            status = resp.status

    except urllib.error.HTTPError as exc:
        return {
            "tools": n,
            "status": exc.code,
            "ok": False,
            "error": f"HTTP {exc.code}",
            "latency_ms": round(
                (time.monotonic() - started) * 1000
            ),
        }

    except Exception as exc:
        return {
            "tools": n,
            "status": None,
            "ok": False,
            "error": type(exc).__name__,
            "latency_ms": round(
                (time.monotonic() - started) * 1000
            ),
        }

    choice = ((data.get("choices") or [{}])[0]).get("message") or {}
    calls = choice.get("tool_calls") or []

    names = [
        ((call.get("function") or {}).get("name"))
        for call in calls
    ]

    target_seen = target in names

    return {
        "tools": n,
        "status": status,
        "ok": status == 200 and target_seen,
        "tool_calls": len(calls),
        "target_seen": target_seen,
        "latency_ms": round(
            (time.monotonic() - started) * 1000
        ),
    }


def main() -> None:
    results = [run(n) for n in (5, 10, 15, 22)]

    print(
        json.dumps(
            {
                "model": MODEL,
                "url": URL,
                "results": results,
            },
            indent=2,
        )
    )

    raise SystemExit(
        1 if any(not result.get("ok") for result in results) else 0
    )


if __name__ == "__main__":
    main()
