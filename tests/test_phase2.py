import json
import unittest
from unittest import mock

from gemini_web2api import _original_generate
from gemini_web2api import protocol
from gemini_web2api import tools
from gemini_web2api import server


class Phase2ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tools = [{
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                    "additionalProperties": False,
                },
            }
        }]

    def test_prompt_prefers_strict_sentinel_protocol(self):
        prompt, _ = tools.messages_to_prompt(
            [{"role": "user", "content": "run pwd"}], self.tools, "auto"
        )
        self.assertIn("@@TOOL_CALL@@", prompt)
        self.assertIn("@@END_TOOL_CALL@@", prompt)
        self.assertIn("arguments MUST be a JSON object", prompt)
        self.assertIn("do not use Markdown fences", prompt)

    def test_schema_validation_rejects_wrong_argument_type(self):
        _, calls = protocol.parse_tool_calls_robust(
            '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":123}}\n@@END_TOOL_CALL@@'
        )
        errors = protocol.validate_tool_calls(calls, self.tools)
        self.assertTrue(errors)
        self.assertIn("expected string", errors[0])

    def test_schema_validation_rejects_unknown_tool(self):
        _, calls = protocol.parse_tool_calls_robust(
            '@@TOOL_CALL@@\n{"name":"rm_all","arguments":{}}\n@@END_TOOL_CALL@@'
        )
        errors = protocol.validate_tool_calls(calls, self.tools)
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown tool", errors[0])

    def test_required_tool_without_call_needs_repair(self):
        self.assertTrue(protocol.response_needs_repair("I cannot do that", [], self.tools, "required"))

    def test_valid_call_does_not_need_repair(self):
        _, calls = protocol.parse_tool_calls_robust(
            '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@'
        )
        self.assertFalse(protocol.response_needs_repair("", calls, self.tools, "auto"))

    def test_generate_repairs_invalid_tool_call_once(self):
        invalid = '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":123}}\n@@END_TOOL_CALL@@'
        valid = '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@'
        protocol.set_tool_context(self.tools, "auto")
        with mock.patch("gemini_web2api._original_generate", side_effect=[invalid, valid]) as upstream:
            result = server.generate("task", "gemini-3.1-pro", False, None, None)
        self.assertEqual(result, valid)
        self.assertEqual(upstream.call_count, 2)
        self.assertIn("Tool Call Repair", upstream.call_args.args[0])
        protocol.clear_tool_context()


if __name__ == "__main__":
    unittest.main()
