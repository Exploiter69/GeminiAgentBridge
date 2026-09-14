import json
import unittest

from gemini_web2api import protocol
from gemini_web2api.context import compact_messages
from gemini_web2api.tool_schema import normalize_tool_definitions


class RoadmapCapabilityTests(unittest.TestCase):
    def test_raw_tool_json_handles_nested_objects_and_braces_in_strings(self):
        text = 'prefix {"name":"write_file","arguments":{"path":"a.json","content":"{\\"x\\": 1}"}} suffix'
        clean, calls = protocol.parse_tool_calls_robust(text)
        self.assertEqual(clean, "prefix  suffix")
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["content"], '{"x": 1}')

    def test_multiple_raw_tool_objects_preserve_order(self):
        text = (
            '{"name":"first","arguments":{"value":1}}\n'
            '{"name":"second","arguments":{"value":2}}'
        )
        _, calls = protocol.parse_tool_calls_robust(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["first", "second"])

    def test_schema_compaction_preserves_semantic_constraints(self):
        original = [{
            "type": "function",
            "function": {
                "name": "edit",
                "description": "A very long description that can be shortened. " * 50,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "README.md"},
                        "mode": {"type": "string", "enum": ["safe", "fast"], "default": "safe"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }]
        compacted = normalize_tool_definitions(original, max_chars=500)
        params = compacted[0]["parameters"]
        self.assertEqual(params["required"], ["path"])
        self.assertFalse(params["additionalProperties"])
        self.assertEqual(params["properties"]["mode"]["enum"], ["safe", "fast"])
        self.assertEqual(params["properties"]["path"]["default"], "README.md")

    def test_context_compaction_keeps_tool_call_and_result_together(self):
        messages = [
            {"role": "system", "content": "system contract"},
            {"role": "user", "content": "old task"},
            {"role": "assistant", "content": "call", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "result"},
            {"role": "user", "content": "current task"},
        ]
        compacted, meta = compact_messages(messages, 80)
        serialized = json.dumps(compacted)
        self.assertTrue(meta["compacted"])
        self.assertIn('"tool_call_id": "1"', serialized)
        self.assertIn('"id": "1"', serialized)
        self.assertIn("current task", serialized)

    def test_tool_choice_none_is_strict(self):
        self.assertEqual(protocol.validate_tool_choice("none", [{"name": "bash"}]), [])
        self.assertTrue(protocol.response_needs_repair(
            '@@TOOL_CALL@@\n{"name":"bash","arguments":{}}\n@@END_TOOL_CALL@@',
            [{"function": {"name": "bash", "arguments": "{}"}}],
            [{"name": "bash", "parameters": {"type": "object"}}],
            "none",
        ))


if __name__ == "__main__":
    unittest.main()
