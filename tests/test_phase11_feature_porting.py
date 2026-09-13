from __future__ import annotations

import json
import unittest

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


class Phase11FeaturePortingTests(unittest.TestCase):
    def test_safe_enum_coercion_accepts_unambiguous_case_and_whitespace(self):
        calls, changes = coerce_tool_call_enums(_call({"mode": " SAFE ", "items": [" b ", "A"]}), [_tool()])
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args, {"mode": "safe", "items": ["B", "A"]})
        self.assertEqual(changes, ["tool_calls[0].arguments"])

    def test_safe_enum_coercion_never_fuzzily_guesses(self):
        calls, changes = coerce_tool_call_enums(_call({"mode": "safer"}), [_tool()])
        self.assertEqual(json.loads(calls[0]["function"]["arguments"])["mode"], "safer")
        self.assertEqual(changes, [])

    def test_safe_enum_coercion_rejects_ambiguous_casefold_matches(self):
        calls, changes = coerce_tool_call_enums(_call({"mode": " SAFE ", "items": ["b"]}), [_tool(["SAFE", "safe"])])
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["mode"], " SAFE ")
        self.assertEqual(args["items"], ["B"])
        self.assertEqual(changes, ["tool_calls[0].arguments"])

    def test_safe_enum_coercion_preserves_non_enum_arguments_and_unknown_tools(self):
        calls = _call({"mode": "FAST", "other": 7}) + [{
            "id": "unknown",
            "type": "function",
            "function": {"name": "unknown", "arguments": json.dumps({"x": "FAST"})},
        }]
        normalized, changes = coerce_tool_call_enums(calls, [_tool()])
        self.assertEqual(json.loads(normalized[0]["function"]["arguments"]), {"mode": "fast", "other": 7})
        self.assertEqual(json.loads(normalized[1]["function"]["arguments"]), {"x": "FAST"})
        self.assertEqual(changes, ["tool_calls[0].arguments"])

    def test_compact_tool_definitions_preserve_callable_schema(self):
        tools = [_tool() for _ in range(40)]
        normalized = normalize_tool_definitions(tools, max_chars=3000)
        self.assertTrue(normalized)
        self.assertTrue(all(item["name"] == "set_mode" for item in normalized))
        self.assertTrue(all("parameters" in item for item in normalized))
        self.assertLessEqual(tool_schema_size(normalized), 3000)

    def test_failed_tool_observation_is_never_equated_with_successful_empty_result(self):
        failed = failed_tool_observation("read_file", ErrorType.TOOL_RESULT_ERROR, "file not found", path="/missing")
        self.assertTrue(is_failed_tool_observation(failed))
        self.assertEqual(preserve_tool_observation(failed), failed)
        self.assertEqual(preserve_tool_observation({"files": []}), {"files": []})
        self.assertFalse(is_failed_tool_observation({"files": []}))

    def test_planner_remains_conservative_and_serializes_only_high_confidence(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the workspace.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
        }]
        high = propose("Read 'src/main.py'", tools)
        self.assertEqual(high.confidence, "high")
        self.assertTrue(proposal_to_tool_call(high).startswith("@@TOOL_CALL@@"))

        low = propose("Read a file and then edit it", tools)
        self.assertEqual(low.confidence, "low")
        self.assertIsNone(proposal_to_tool_call(low))
        self.assertFalse(PlannerProposal("medium", "ambiguous").should_synthesize)


if __name__ == "__main__":
    unittest.main()
