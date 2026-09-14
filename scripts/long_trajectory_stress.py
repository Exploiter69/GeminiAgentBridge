#!/usr/bin/env python3
"""Deterministic long-horizon stress test for context/tool continuity."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gemini_web2api.context import compact_messages
from gemini_web2api.protocol import parse_tool_calls_robust, validate_tool_calls


def build_messages(turns: int = 200) -> list[dict]:
    messages = [{"role": "system", "content": "You are editing the current repository. Never lose workspace identity."}]
    for i in range(turns):
        messages.append({"role": "user", "content": f"turn {i}: inspect and update the current task"})
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"src/file_{i}.py"})}}],
        })
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "name": "read_file", "content": f"FILE_{i}_OBSERVATION"})
    messages.append({"role": "user", "content": "FINAL_TASK: update the current repository and verify tests"})
    return messages


def main() -> int:
    messages = build_messages()
    compacted, metadata = compact_messages(messages, 24000)
    serialized = "\n".join(str(message) for message in compacted)
    required = ("FINAL_TASK", "FILE_199_OBSERVATION", '"path": "src/file_199.py"')
    context_ok = metadata["compacted"] and all(marker in serialized for marker in required)

    tool_text = '@@TOOL_CALL@@ {"name":"edit_file","arguments":{"path":"src/file_199.py","content":"{ nested: true }"}} @@END_TOOL_CALL@@'
    clean, calls = parse_tool_calls_robust(tool_text)
    protocol_ok = clean == "" and len(calls) == 1 and not validate_tool_calls(calls, [{
        "type": "function",
        "function": {"name": "edit_file", "parameters": {
            "type": "object", "required": ["path", "content"],
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        }},
    }])

    report = {
        "turns": 200,
        "messages": len(messages),
        "compacted_messages": len(compacted),
        "context": metadata,
        "context_continuity_pass": context_ok,
        "tool_protocol_pass": protocol_ok,
        "pass": context_ok and protocol_ok,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
