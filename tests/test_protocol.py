import json
import unittest

from gemini_web2api.protocol import parse_tool_calls_robust
from gemini_web2api.tools import messages_to_prompt, parse_tool_calls


class ToolProtocolTests(unittest.TestCase):
    def test_legacy_fenced_call(self):
        text = '```tool_call\n{"name":"read_file","arguments":{"path":"a.py"}}\n```'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(clean, "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a.py"})

    def test_strict_sentinel_call(self):
        text = 'before\n@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@\nafter'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(clean, "before\n\nafter")
        self.assertEqual(calls[0]["function"]["name"], "bash")

    def test_multiple_calls_preserve_order(self):
        text = '@@TOOL_CALL@@\n{"name":"a","arguments":{}}\n@@END_TOOL_CALL@@\n@@TOOL_CALL@@\n{"name":"b","arguments":{"x":1}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["a", "b"])

    def test_duplicate_call_is_removed(self):
        block = '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@'
        clean, calls = parse_tool_calls_robust(block + "\n" + block)
        self.assertEqual(len(calls), 1)
        self.assertEqual(clean, "")

    def test_string_arguments_are_normalized(self):
        text = '```tool_call\n{"name":"x","arguments":"{\\"value\\":42}"}\n```'
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"value": 42})

    def test_malformed_call_is_fail_closed(self):
        text = 'prefix @@TOOL_CALL@@\n{"name":"bash","arguments":}\n@@END_TOOL_CALL@@ suffix'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(calls, [])
        self.assertIn("@@TOOL_CALL@@", clean)

    def test_missing_name_is_rejected(self):
        text = '```tool_call\n{"arguments":{"x":1}}\n```'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(calls, [])
        self.assertIn("tool_call", clean)

    def test_ids_are_deterministic(self):
        text = '```tool_call\n{"name":"bash","arguments":{"command":"pwd"}}\n```'
        _, first = parse_tool_calls_robust(text)
        _, second = parse_tool_calls_robust(text)
        self.assertEqual(first[0]["id"], second[0]["id"])

    def test_declared_schema_is_enforced(self):
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}}}]
        messages_to_prompt([{"role": "user", "content": "read"}], tools, "auto")
        clean, calls = parse_tool_calls('```tool_call\n{"name":"read_file","arguments":{"path":"a.py"}}\n```')
        self.assertEqual(clean, "")
        self.assertEqual(calls[0]["function"]["name"], "read_file")

    def test_unknown_tool_is_rejected(self):
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
        messages_to_prompt([{"role": "user", "content": "read"}], tools, "auto")
        with self.assertRaises(ValueError):
            parse_tool_calls('```tool_call\n{"name":"shell","arguments":{"command":"id"}}\n```')

    def test_required_tool_choice_rejects_text_only(self):
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
        messages_to_prompt([{"role": "user", "content": "read"}], tools, "required")
        with self.assertRaises(ValueError):
            parse_tool_calls("plain text")


if __name__ == "__main__":
    unittest.main()
