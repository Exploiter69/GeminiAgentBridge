"""Deterministic Phase 11 feature-port benchmark.

This benchmark executes no downstream tools and uses only in-memory fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gemini_web2api.feature_porting import coerce_tool_call_enums
from gemini_web2api.planner import propose, proposal_to_tool_call
from gemini_web2api.recovery import ErrorType, failed_tool_observation, is_failed_tool_observation
from gemini_web2api.tool_schema import normalize_tool_definitions, tool_schema_size


def tool():
    return {
        "type": "function",
        "function": {
            "name": "set_mode",
            "description": "Set the execution mode.",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}},
                "required": ["mode"],
            },
        },
    }


def main() -> int:
    checks: dict[str, bool] = {}

    calls = [{"function": {"name": "set_mode", "arguments": json.dumps({"mode": " SAFE "})}}]
    normalized, changes = coerce_tool_call_enums(calls, [tool()])
    checks["safe_enum_coercion"] = json.loads(normalized[0]["function"]["arguments"])["mode"] == "safe" and bool(changes)

    untouched, no_changes = coerce_tool_call_enums(
        [{"function": {"name": "set_mode", "arguments": json.dumps({"mode": "safer"})}}], [tool()]
    )
    checks["no_fuzzy_enum_guess"] = json.loads(untouched[0]["function"]["arguments"])["mode"] == "safer" and not no_changes

    compact = normalize_tool_definitions([tool()] * 100, max_chars=2000)
    checks["compact_tool_schema"] = bool(compact) and tool_schema_size(compact) <= 2000

    failed = failed_tool_observation("set_mode", ErrorType.TOOL_RESULT_ERROR, "downstream failure")
    checks["failed_observation_preserved"] = is_failed_tool_observation(failed) and failed["status"] == "error"

    planner_tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    }]
    proposal = propose("Read 'src/main.py'", planner_tools)
    checks["planner_high_confidence_contract"] = proposal.confidence == "high" and proposal_to_tool_call(proposal) is not None
    checks["planner_multi_step_guard"] = proposal_to_tool_call(propose("Read it and then edit it", planner_tools)) is None

    passed = sum(checks.values())
    total = len(checks)
    print(json.dumps({"phase": 11, "passed": passed, "total": total, "checks": checks}, sort_keys=True))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
