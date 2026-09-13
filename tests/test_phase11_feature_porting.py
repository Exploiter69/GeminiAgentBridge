from __future__ import annotations

import json

from gemini_web2api.feature_porting import coerce_tool_call_enums
from gemini_web2api.planner import PlannerProposal, propose, proposal_to_tool_call
from gemini_web2api.recovery import (
    ErrorType,
    failed_tool_observation,
    is_failed_tool_observation,
    preserve_tool_observation,
)
from gemini_web2api.tool_schema import normalize_tool_definitions, tool_schema_size


def _tool(enum_values=None):
    return {
        "type": "function",
        "function": {
            "name": "set_mode",
            "description": "Set the execution mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": enum_values or ["fast", "safe"]},
                    "items": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["A", "B"]},
                    },
                },
                "required": ["mode"],
            },
        },
    }


def _call(arguments):
    return [{
        "id": "call_test",
        "type": "function",
        "function": {"name": "set_mode", "arguments": json.dumps(arguments)},
    }]


def test_safe_enum_coercion_accepts_unambiguous_case_and_whitespace():
    calls, changes = coerce_tool_call_enums(_call({"mode": " SAFE ", "items": [" b ", "A"]}), [_tool()])
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"mode": "safe", "items": ["B", "A"]}
    assert changes == ["tool_calls[0].arguments"]


def test_safe_enum_coercion_never_fuzzily_guesses():
    calls, changes = coerce_tool_call_enums(_call({"mode": "safer"}), [_tool()])
    assert json.loads(calls[0]["function"]["arguments"])["mode"] == "safer"
    assert changes == []


def test_safe_enum_coercion_rejects_ambiguous_casefold_matches():
    calls, changes = coerce_tool_call_enums(_call({"mode": "safe"}), [_tool(["SAFE", "safe"])])
    assert json.loads(calls[0]["function"]["arguments"])["mode"] == "safe"
    assert changes == []


def test_safe_enum_coercion_preserves_non_enum_arguments_and_unknown_tools():
    calls = _call({"mode": "FAST", "other": 7}) + [{
        "id": "unknown",
        "type": "function",
        "function": {"name": "unknown", "arguments": json.dumps({"x": "FAST"})},
    }]
    normalized, changes = coerce_tool_call_enums(calls, [_tool()])
    assert json.loads(normalized[0]["function"]["arguments"]) == {"mode": "fast", "other": 7}
    assert json.loads(normalized[1]["function"]["arguments"]) == {"x": "FAST"}
    assert changes == ["tool_calls[0].arguments"]


def test_compact_tool_definitions_preserve_callable_schema():
    tools = [_tool() for _ in range(40)]
    normalized = normalize_tool_definitions(tools, max_chars=3000)
    assert normalized
    assert all(item["name"] == "set_mode" for item in normalized)
    assert all("parameters" in item for item in normalized)
    assert tool_schema_size(normalized) <= 3000


def test_failed_tool_observation_is_never_equated_with_successful_empty_result():
    failed = failed_tool_observation("read_file", ErrorType.TOOL_RESULT_ERROR, "file not found", path="/missing")
    assert is_failed_tool_observation(failed)
    assert preserve_tool_observation(failed) == failed
    assert preserve_tool_observation({"files": []}) == {"files": []}
    assert not is_failed_tool_observation({"files": []})


def test_planner_remains_conservative_and_serializes_only_high_confidence():
    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    }]
    high = propose("Read 'src/main.py'", tools)
    assert high.confidence == "high"
    assert proposal_to_tool_call(high).startswith("@@TOOL_CALL@@")

    low = propose("Read a file and then edit it", tools)
    assert low.confidence == "low"
    assert proposal_to_tool_call(low) is None
    assert PlannerProposal("medium", "ambiguous").should_synthesize is False
