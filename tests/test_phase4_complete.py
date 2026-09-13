import copy
import json
import unittest

from gemini_web2api.context import compact_messages
from gemini_web2api.grounding import GroundingFacts
from gemini_web2api.observability import request_summary, response_summary
from gemini_web2api.protocol import parse_tool_calls_robust, validate_tool_calls
from gemini_web2api.tool_schema import normalize_tool_definitions, tool_schema_size
from gemini_web2api.tools import messages_to_prompt


def make_tools(count):
    return [{"type": "function", "function": {"name": f"tool_{i}", "description": "Verbose tool description " * 8, "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Target path"}, "mode": {"type": "string", "enum": ["read", "write", "inspect"]}}, "required": ["path"], "additionalProperties": False}}} for i in range(count)]


class ToolSchemaNormalizationTests(unittest.TestCase):
    def test_does_not_mutate_input(self):
        tools = make_tools(5)
        original = copy.deepcopy(tools)
        normalize_tool_definitions(tools)
        self.assertEqual(tools, original)

    def test_5_10_15_22_tools_preserve_callable_schema(self):
        for count in (5, 10, 15, 22):
            normalized = normalize_tool_definitions(make_tools(count))
            self.assertEqual(len(normalized), count)
            self.assertEqual({x["name"] for x in normalized}, {f"tool_{i}" for i in range(count)})
            for tool in normalized:
                params = tool["parameters"]
                self.assertEqual(params["type"], "object")
                self.assertIn("path", params["properties"])
                self.assertEqual(params["properties"]["path"]["type"], "string")
                self.assertIn("path", params["required"])
            self.assertLess(tool_schema_size(normalized), 30000)

    def test_prompt_contains_all_tool_names_and_argument_schema(self):
        prompt, _ = messages_to_prompt([{"role": "user", "content": "Use the tools."}], make_tools(22), "auto")
        for i in range(22):
            self.assertIn(f"tool_{i}", prompt)
        self.assertIn('"path"', prompt)
        self.assertIn('"required"', prompt)


class ProtocolRobustnessTests(unittest.TestCase):
    def test_multiple_protocol_forms_are_parsed(self):
        text = '@@TOOL_CALL@@\n{"name":"tool_1","arguments":{"path":"a"}}\n@@END_TOOL_CALL@@\n```tool_call\n{"name":"tool_2","arguments":{"path":"b"}}\n```'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(clean, "")
        self.assertEqual([c["function"]["name"] for c in calls], ["tool_1", "tool_2"])

    def test_validation_rejects_unknown_and_missing_required(self):
        tools = make_tools(1)
        self.assertTrue(validate_tool_calls([{"function": {"name": "missing", "arguments": "{}"}}], tools))
        self.assertTrue(validate_tool_calls([{"function": {"name": "tool_0", "arguments": "{}"}}], tools))


class ContextGroundingTests(unittest.TestCase):
    def test_compaction_preserves_latest_tool_state(self):
        messages = [{"role": "system", "content": "contract"}, {"role": "user", "content": "old " * 80}, {"role": "assistant", "content": "old answer " * 80}, {"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": "{}"}}], "content": ""}, {"role": "tool", "name": "read_file", "content": "alpha beta gamma"}, {"role": "user", "content": "continue from sample.txt"}]
        result, meta = compact_messages(messages, 260)
        rendered = json.dumps(result)
        self.assertTrue(meta["compacted"])
        self.assertIn("sample.txt", rendered)
        self.assertIn("alpha beta gamma", rendered)

    def test_grounding_is_explicit_only(self):
        facts = GroundingFacts.from_request({"metadata": {"grounding": {"runtime_cwd": "/tmp/work", "known_files": ["a.py"]}}})
        self.assertTrue(facts.is_explicit)
        self.assertIn("/tmp/work", facts.to_prompt())
        self.assertFalse(GroundingFacts.from_request({"messages": []}).is_explicit)


class ObservabilityTests(unittest.TestCase):
    def test_query_credentials_are_not_in_summary(self):
        start = request_summary("POST", "/v1/chat/completions?key=super-secret", "abc", 123)
        end = response_summary("abc", 502, 12, "gemini-3.1-pro", ["read_file"])
        self.assertNotIn("super-secret", str(start))
        self.assertNotIn("arguments", str(end))
        self.assertEqual(start["path"], "/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
