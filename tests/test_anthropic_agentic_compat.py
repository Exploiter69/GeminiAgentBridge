import unittest

from gemini_web2api.anthropic_compat import (
    anthropic_messages_to_openai,
    anthropic_tool_choice_to_openai,
    anthropic_tools_to_openai,
)


class AnthropicAgenticCompatibilityTests(unittest.TestCase):
    def test_named_tool_choice_uses_internal_function_choice(self):
        choice = anthropic_tool_choice_to_openai(
            {"type": "tool", "name": "read_file"}
        )
        self.assertEqual(
            choice,
            {"function": {"name": "read_file"}},
        )

    def test_named_tool_choice_survives_full_request_conversion(self):
        req = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Read README.md"}],
            "tools": [{
                "name": "read_file",
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }],
            "tool_choice": {"type": "tool", "name": "read_file"},
        }
        messages, tools, choice = anthropic_messages_to_openai(req)
        self.assertEqual(len(messages), 1)
        self.assertEqual(tools[0]["function"]["name"], "read_file")
        self.assertEqual(
            choice,
            {"function": {"name": "read_file"}},
        )

    def test_unsupported_server_tool_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "unsupported Anthropic tool type"):
            anthropic_tools_to_openai([{
                "type": "computer_20250124",
                "name": "computer",
            }])

    def test_invalid_tool_choice_is_not_silently_changed_to_auto(self):
        with self.assertRaisesRegex(ValueError, "unsupported Anthropic tool_choice"):
            anthropic_tool_choice_to_openai({"type": "bogus"})

    def test_exact_duplicate_tool_calls_are_deduplicated(self):
        from gemini_web2api.protocol import parse_tool_calls_robust
        text = (
            '@@TOOL_CALL@@\\n{"name":"write_file","arguments":{"path":"x","content":"a"}}\\n'
            '@@END_TOOL_CALL@@\\n'
            '@@TOOL_CALL@@\\n{"name":"write_file","arguments":{"path":"x","content":"a"}}\\n'
            '@@END_TOOL_CALL@@'
        )
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
