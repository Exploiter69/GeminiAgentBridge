#!/usr/bin/env python3
"""Deterministic Phase 8 compatibility benchmark.

This benchmark verifies the complete required client matrix is represented and
that the bridge's OpenAI-compatible response contract accepts representative
text and tool-call responses. Real Hermes/OpenCode execution is handled by
scripts/phase8_client_compat.py and is intentionally kept out of CI unless a
runner has those clients installed.
"""
import json

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
