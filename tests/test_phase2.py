import http.client
import json
import threading
import unittest
from unittest import mock

from gemini_web2api import protocol
from gemini_web2api import server
from gemini_web2api import tools
from gemini_web2api.config import CONFIG


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

    def test_prompt_uses_canonical_tool_call_protocol(self):
        prompt, _ = tools.messages_to_prompt(
            [{"role": "user", "content": "run pwd"}], self.tools, "auto"
        )
        self.assertIn("```tool_call", prompt)
        self.assertIn('"name": "func_name"', prompt)
        self.assertIn('"arguments": {...}', prompt)
        self.assertIn("output ONLY the tool_call block(s)", prompt)

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

    def test_chat_completion_returns_openai_tool_call(self):
        original_config = dict(CONFIG)
        CONFIG["api_keys"] = []
        bridge = server.ThreadedServer(("127.0.0.1", 0), server.GeminiHandler)
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        bridge.allow_reuse_address = True
        thread.start()
        try:
            valid = '```tool_call\n{"name":"bash","arguments":{"command":"pwd"}}\n```'
            with mock.patch("gemini_web2api.server.generate", return_value=valid) as upstream:
                connection = http.client.HTTPConnection("127.0.0.1", bridge.server_address[1], timeout=5)
                connection.request(
                    "POST",
                    "/v1/chat/completions",
                    body=json.dumps({
                        "model": "gemini-3.1-pro",
                        "messages": [{"role": "user", "content": "run pwd"}],
                        "tools": self.tools,
                    }),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                body = json.loads(response.read().decode())
                connection.close()

            self.assertEqual(response.status, 200)
            message = body["choices"][0]["message"]
            self.assertIsNone(message["content"])
            self.assertEqual(message["tool_calls"][0]["function"]["name"], "bash")
            self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"command": "pwd"})
            self.assertEqual(upstream.call_count, 1)
        finally:
            bridge.shutdown()
            bridge.server_close()
            thread.join(timeout=5)
            CONFIG.clear()
            CONFIG.update(original_config)
            protocol.clear_tool_context()


if __name__ == "__main__":
    unittest.main()
