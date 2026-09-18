import http.client
import json
import threading
import unittest
from unittest import mock

from gemini_web2api import protocol
from gemini_web2api import server
from gemini_web2api import tools
from gemini_web2api.config import CONFIG


class Phase3AgentContractTests(unittest.TestCase):
    def setUp(self):
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a command",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def _call(self, path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        connection.close()
        return response.status, body

    def setUp_server(self):
        original_config = dict(CONFIG)
        CONFIG["api_keys"] = []
        CONFIG["upstream_backend"] = "legacy"
        bridge = server.ThreadedServer(("127.0.0.1", 0), server.GeminiHandler)
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        thread.start()
        self.bridge, self.thread, self.port, self.original_config = bridge, thread, bridge.server_address[1], original_config

    def tearDown_server(self):
        if hasattr(self, "bridge"):
            self.bridge.shutdown()
            self.bridge.server_close()
            self.thread.join(timeout=5)
            CONFIG.clear()
            CONFIG.update(self.original_config)
            protocol.clear_tool_context()

    def test_multi_tool_response_preserves_order_and_unique_ids(self):
        text = (
            '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"a.py"}}\n@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@'
        )
        _, calls = protocol.parse_tool_calls_robust(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["read_file", "bash"])
        self.assertEqual(len({c["id"] for c in calls}), 2)

    def test_duplicate_tool_call_is_executed_once_at_protocol_boundary(self):
        block = '@@TOOL_CALL@@\n{"name":"bash","arguments":{"command":"pwd"}}\n@@END_TOOL_CALL@@'
        _, calls = protocol.parse_tool_calls_robust(block + "\n" + block)
        self.assertEqual(len(calls), 1)

    def test_chat_completion_returns_valid_openai_tool_calls(self):
        self.setUp_server()
        try:
            valid = '```tool_call\n{"name":"bash","arguments":{"command":"pwd"}}\n```'
            with mock.patch("gemini_web2api.server.generate", return_value=valid) as upstream:
                status, body = self._call("/v1/chat/completions", {
                    "model": "gemini-3.1-pro",
                    "messages": [{"role": "user", "content": "run pwd"}],
                    "tools": self.tools,
                })
            self.assertEqual(status, 200)
            message = body["choices"][0]["message"]
            self.assertEqual(body["choices"][0]["finish_reason"], "tool_calls")
            self.assertIsNone(message["content"])
            self.assertEqual(message["tool_calls"][0]["function"]["name"], "bash")
            self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"command": "pwd"})
            self.assertEqual(upstream.call_count, 1)
        finally:
            self.tearDown_server()

    def test_responses_api_preserves_tool_result_across_turns(self):
        self.setUp_server()
        try:
            first = '```tool_call\n{"name":"read_file","arguments":{"path":"app.py"}}\n```'
            with mock.patch("gemini_web2api.server.generate", return_value=first):
                status, body = self._call("/v1/responses", {
                    "model": "gemini-3.1-pro",
                    "input": [{"type": "input_text", "text": "Read app.py"}],
                    "tools": [{"type": "function", "name": "read_file", "parameters": self.tools[0]["function"]["parameters"]}],
                })
            self.assertEqual(status, 200)
            call = next(item for item in body["output"] if item["type"] == "function_call")
            output = [{"type": "function_call_output", "call_id": call["call_id"], "name": "read_file", "output": "print('ok')"}]
            output.insert(0, {"type": "message", "role": "assistant", "content": [{"type": "function_call", "call_id": call["call_id"], "name": "read_file", "arguments": call["arguments"]}]})
            with mock.patch("gemini_web2api.server.generate", return_value="The file contains print('ok').") as upstream:
                status, body2 = self._call("/v1/responses", {
                    "model": "gemini-3.1-pro",
                    "input": output,
                    "tools": [{"type": "function", "name": "read_file", "parameters": self.tools[0]["function"]["parameters"]}],
                })
            self.assertEqual(status, 200)
            self.assertIn("print('ok')", body2["output"][0]["content"][0]["text"])
            prompt = upstream.call_args.args[0]
            self.assertIn("Tool result for read_file", prompt)
            self.assertIn("print('ok')", prompt)
        finally:
            self.tearDown_server()

    def test_responses_api_resolves_tool_name_when_function_call_output_omits_name(self):
        # Regression: the real OpenAI Responses API schema for
        # "function_call_output" carries only {type, call_id, output} - it
        # has NO "name" field (unlike this test file's other fixtures, which
        # add "name" defensively). The bridge must still resolve the tool
        # name via call_id -> the preceding function_call's name, the same
        # mechanism that fixes this for Chat Completions tool messages.
        self.setUp_server()
        try:
            first = '```tool_call\n{"name":"read_file","arguments":{"path":"app.py"}}\n```'
            with mock.patch("gemini_web2api.server.generate", return_value=first):
                status, body = self._call("/v1/responses", {
                    "model": "gemini-3.1-pro",
                    "input": [{"type": "input_text", "text": "Read app.py"}],
                    "tools": [{"type": "function", "name": "read_file", "parameters": self.tools[0]["function"]["parameters"]}],
                })
            self.assertEqual(status, 200)
            call = next(item for item in body["output"] if item["type"] == "function_call")

            # Realistic Responses API shape: no "name" on function_call_output.
            output = [
                {"type": "message", "role": "assistant", "content": [
                    {"type": "function_call", "call_id": call["call_id"], "name": "read_file", "arguments": call["arguments"]}
                ]},
                {"type": "function_call_output", "call_id": call["call_id"], "output": "print('ok')"},
            ]
            with mock.patch("gemini_web2api.server.generate", return_value="The file contains print('ok').") as upstream:
                status, body2 = self._call("/v1/responses", {
                    "model": "gemini-3.1-pro",
                    "input": output,
                    "tools": [{"type": "function", "name": "read_file", "parameters": self.tools[0]["function"]["parameters"]}],
                })
            self.assertEqual(status, 200)
            prompt = upstream.call_args.args[0]
            self.assertIn("Tool result for read_file", prompt)
            self.assertNotIn("Tool result for ]", prompt)
            self.assertNotIn("Tool result for :", prompt)
        finally:
            self.tearDown_server()

    def test_responses_api_preserves_top_level_function_call_input(self):
        self.setUp_server()
        try:
            with mock.patch(
                "gemini_web2api.server.generate",
                return_value="Tool result acknowledged.",
            ) as upstream:
                status, body = self._call("/v1/responses", {
                    "model": "gemini-3.1-pro",
                    "input": [
                        {
                            "type": "function_call",
                            "call_id": "call_read",
                            "name": "read_file",
                            "arguments": '{"path":"app.py"}',
                        },
                        {
                            "type": "function_call_output",
                            "call_id": "call_read",
                            "name": "read_file",
                            "output": "print('ok')",
                        },
                    ],
                    "tools": [
                        {
                            "type": "function",
                            "name": "read_file",
                            "parameters": self.tools[0]["function"]["parameters"],
                        }
                    ],
                })

            self.assertEqual(status, 200)
            prompt = upstream.call_args.args[0]

            # The prior function call must survive as an assistant tool call.
            self.assertIn("[Assistant]:", prompt)
            self.assertIn('"name": "read_file"', prompt)
            self.assertIn('"path":"app.py"', prompt)
            self.assertIn("Tool result for read_file", prompt)
            self.assertIn("print('ok')", prompt)

            # The corresponding observation must remain a tool result.
            self.assertIn("Tool result for read_file", prompt)
            self.assertIn("print('ok')", prompt)

            self.assertEqual(
                body["output"][0]["type"],
                "message",
            )
            self.assertIn(
                "Tool result acknowledged.",
                body["output"][0]["content"][0]["text"],
            )
        finally:
            self.tearDown_server()

    def test_tool_messages_are_not_lost_when_no_tools_are_requested(self):
        prompt, _ = tools.messages_to_prompt([
            {"role": "user", "content": "hello"},
            {"role": "tool", "name": "bash", "content": "/home/user/project"},
        ], None, "none")
        self.assertIn("Tool result for bash", prompt)
        self.assertIn("/home/user/project", prompt)

    def test_tool_result_name_is_resolved_from_tool_call_id_when_name_is_absent(self):
        # Regression: a standard OpenAI Chat Completions tool-result message
        # carries "tool_call_id", not "name" ("name" belongs to the deprecated
        # function-role message shape). Real clients such as OpenCode send
        # exactly this shape. Before this fix, messages_to_prompt rendered
        # every such result as an anonymous "[Tool result for ]" block,
        # making concurrent/sequential tool calls indistinguishable to the
        # model as soon as more than one tool call appeared in a trajectory.
        prompt, _ = tools.messages_to_prompt([
            {"role": "user", "content": "list *.py then read the first one"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "glob", "arguments": '{"pattern": "*.py"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "a.py\nb.py"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_2", "content": "print(1)"},
        ], None, "auto")
        self.assertIn("Tool result for glob", prompt)
        self.assertIn("Tool result for read_file", prompt)
        self.assertNotIn("Tool result for ]", prompt)
        self.assertNotIn("Tool result for :", prompt)

    def test_tool_context_is_reset_by_each_prompt_build(self):
        protocol.set_tool_context(self.tools, "required")
        tools.messages_to_prompt([{"role": "user", "content": "plain"}], None, "none")
        defs, choice = protocol.get_tool_context()
        self.assertEqual(defs, [])
        self.assertEqual(choice, "none")
        protocol.clear_tool_context()


if __name__ == "__main__":
    unittest.main()
