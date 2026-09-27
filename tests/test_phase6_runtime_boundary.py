import sys
import types
import unittest

from gemini_web2api.phase4_runtime import _state, install_phase4_runtime
from gemini_web2api import protocol


READ_FILE = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

SEARCH = {
    "type": "function",
    "function": {
        "name": "search",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class RuntimeToolParserBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.module_name = "_phase6_runtime_boundary_fake"
        module = types.ModuleType(self.module_name)
        module.generate = lambda *_a, **_k: "unused"
        module.log = lambda _msg: None
        sys.modules[self.module_name] = module

        class DummyHandler:
            __module__ = self.module_name

            def do_POST(self):
                return None

        install_phase4_runtime(DummyHandler)
        self.module = module
        protocol.clear_tool_context()

    def tearDown(self):
        protocol.clear_tool_context()
        for attr in ("grounding", "tool_defs", "tool_choice"):
            if hasattr(_state, attr):
                delattr(_state, attr)
        sys.modules.pop(self.module_name, None)

    def test_invalid_unknown_tool_fails_closed(self):
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "auto"

        text = (
            '@@TOOL_CALL@@\n'
            '{"name":"delete_file","arguments":{"path":"x"}}\n'
            '@@END_TOOL_CALL@@'
        )

        with self.assertRaisesRegex(ValueError, "invalid tool call protocol"):
            self.module.parse_tool_calls(text)

    def test_invalid_arguments_fail_closed(self):
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "auto"

        text = (
            '@@TOOL_CALL@@\n'
            '{"name":"read_file","arguments":{}}\n'
            '@@END_TOOL_CALL@@'
        )

        with self.assertRaisesRegex(ValueError, "invalid tool call protocol"):
            self.module.parse_tool_calls(text)

    def test_tool_choice_none_fails_closed(self):
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "none"

        text = (
            '@@TOOL_CALL@@\n'
            '{"name":"read_file","arguments":{"path":"x"}}\n'
            '@@END_TOOL_CALL@@'
        )

        with self.assertRaisesRegex(ValueError, "invalid tool call protocol"):
            self.module.parse_tool_calls(text)

    def test_named_tool_choice_fails_closed_for_wrong_tool(self):
        _state.tool_defs = [READ_FILE, SEARCH]
        _state.tool_choice = {
            "type": "function",
            "function": {"name": "read_file"},
        }

        text = (
            '@@TOOL_CALL@@\n'
            '{"name":"search","arguments":{"query":"x"}}\n'
            '@@END_TOOL_CALL@@'
        )

        with self.assertRaisesRegex(ValueError, "invalid tool call protocol"):
            self.module.parse_tool_calls(text)

    def test_valid_multiple_calls_preserve_order(self):
        _state.tool_defs = [READ_FILE, SEARCH]
        _state.tool_choice = "auto"

        text = (
            '@@TOOL_CALL@@\n'
            '{"name":"search","arguments":{"query":"alpha"}}\n'
            '@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n'
            '{"name":"read_file","arguments":{"path":"a.txt"}}\n'
            '@@END_TOOL_CALL@@'
        )

        clean, calls = self.module.parse_tool_calls(text)

        self.assertEqual(
            [call["function"]["name"] for call in calls],
            ["search", "read_file"],
        )
        self.assertNotIn("@@TOOL_CALL@@", clean)

    def test_valid_parser_does_not_fabricate_or_rewrite_calls(self):
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "auto"

        text = """@@TOOL_CALL@@
{"name":"read_file","arguments":{"path":"exact.txt"}}
@@END_TOOL_CALL@@"""

        clean, calls = self.module.parse_tool_calls(text)

        self.assertEqual(clean, "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read_file")

        import json
        self.assertEqual(
            json.loads(calls[0]["function"]["arguments"]),
            {"path": "exact.txt"},
        )
