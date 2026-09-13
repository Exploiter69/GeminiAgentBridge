#!/usr/bin/env python3
"""Deterministic Phase 8 compatibility benchmark."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gemini_web2api.client_compat import (
    COMPATIBILITY_MATRIX,
    validate_chat_completion,
    validate_models_response,
)


def main():
    text = {
        "object": "chat.completion",
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    }
    tool = {
        "object": "chat.completion",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_phase8",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"sample.txt"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }
    models = {"object": "list", "data": [{"id": "gemini-3.6-flash"}]}
    checks = {
        "matrix_cases": len(COMPATIBILITY_MATRIX),
        "text_completion_contract": not validate_chat_completion(text),
        "tool_completion_contract": not validate_chat_completion(tool),
        "models_contract": not validate_models_response(models),
    }
    checks["all_pass"] = all(checks.values())
    print(json.dumps(checks, indent=2))
    return 0 if checks["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
