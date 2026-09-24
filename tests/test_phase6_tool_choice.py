import json
import sys
import types
import unittest

from gemini_web2api.phase4_runtime import _state, install_phase4_runtime
from gemini_web2api.protocol import (
    parse_tool_calls_robust,
    response_needs_repair,
    validate_tool_calls,
    validate_tool_choice,
)
from gemini_web2api.tools import _build_tool_choice_instruction, messages_to_prompt


READ_FILE = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "mode": {"type": "string", "enum": ["text", "lines"]},
            },
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


class ToolChoiceInstructionTests(unittest.TestCase):
    def test_none_forbids_tools_in_prompt(self):
        prompt, _ = messages_to_prompt([{"role": "user", "content": "hello"}], [READ_FILE], "none")
        self.assertNotIn("Available tools:", prompt)
        self.assertIn("Do NOT call any tools", _build_tool_choice_instruction("none", [READ_FILE]))

    def test_required_is_explicit(self):
        self.assertIn("MUST call at least one tool", _build_tool_choice_instruction("required", [READ_FILE]))

    def test_named_required_tool_is_explicit(self):
        choice = {"type": "function", "function": {"name": "read_file"}}
        text = _build_tool_choice_instruction(choice, [READ_FILE, SEARCH])
        self.assertIn('MUST call the tool "read_file"', text)

    def test_invalid_named_choice_is_rejected(self):
        choice = {"type": "function", "function": {"name": "missing"}}
        self.assertTrue(validate_tool_choice(choice, [READ_FILE]))

    def test_required_without_tools_is_rejected(self):
        self.assertTrue(validate_tool_choice("required", []))

    def test_auto_none_and_required_are_valid_modes(self):
        for choice in ("auto", "none", "required"):
            self.assertFalse(validate_tool_choice(choice, [READ_FILE]))


class ParsingAndValidationTests(unittest.TestCase):
    def test_malformed_json_is_not_accepted(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":}}\n@@END_TOOL_CALL@@'
        clean, calls = parse_tool_calls_robust(text)
        self.assertEqual(calls, [])
        self.assertIn("@@TOOL_CALL@@", clean)
        self.assertTrue(response_needs_repair(text, calls, [READ_FILE], "auto"))

    def test_wrong_tool_name_is_rejected(self):
        text = '@@TOOL_CALL@@\n{"name":"delete_file","arguments":{"path":"x"}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        errors = validate_tool_calls(calls, [READ_FILE])
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown tool", errors[0])

    def test_missing_required_argument_is_rejected(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertTrue(validate_tool_calls(calls, [READ_FILE]))

    def test_enum_mismatch_is_rejected(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"x","mode":"binary"}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        errors = validate_tool_calls(calls, [READ_FILE])
        self.assertIn("value is not allowed", errors[0])

    def test_extra_property_is_rejected(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"x","secret":"no"}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        errors = validate_tool_calls(calls, [READ_FILE])
        self.assertIn("unexpected field", errors[0])

    def test_stringified_arguments_are_normalized(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":"{\\"path\\":\\"x\\"}"}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "x"})
        self.assertEqual(validate_tool_calls(calls, [READ_FILE]), [])

    def test_empty_arguments_are_valid_when_schema_allows_them(self):
        no_args = {"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}
        text = '@@TOOL_CALL@@\n{"name":"ping","arguments":{}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual(validate_tool_calls(calls, [no_args]), [])

    def test_ordered_multi_tool_calls_are_preserved(self):
        text = (
            '@@TOOL_CALL@@\n{"name":"search","arguments":{"query":"alpha"}}\n@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"a.txt"}}\n@@END_TOOL_CALL@@'
        )
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["search", "read_file"])

    def test_exact_duplicate_calls_are_preserved_without_reordering(self):
        text = (
            '@@TOOL_CALL@@\n{"name":"search","arguments":{"query":"alpha"}}\n@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n{"name":"search","arguments":{"query":"alpha"}}\n@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"a.txt"}}\n@@END_TOOL_CALL@@'
        )
        _, calls = parse_tool_calls_robust(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["search", "read_file"])

    def test_required_detects_missing_call(self):
        self.assertTrue(response_needs_repair("plain answer", [], [READ_FILE], "required"))

    def test_none_rejects_tool_call(self):
        text = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"x"}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertTrue(response_needs_repair(text, calls, [READ_FILE], "none"))

    def test_named_required_detects_wrong_tool(self):
        choice = {"type": "function", "function": {"name": "read_file"}}
        text = '@@TOOL_CALL@@\n{"name":"search","arguments":{"query":"x"}}\n@@END_TOOL_CALL@@'
        _, calls = parse_tool_calls_robust(text)
        self.assertTrue(response_needs_repair(text, calls, [READ_FILE, SEARCH], choice))


class RuntimeToolChoiceTests(unittest.TestCase):
    def _install_with(self, generate):
        module_name = "_phase6_fake_server"
        module = types.ModuleType(module_name)
        module.generate = generate
        module.log = lambda _msg: None
        sys.modules[module_name] = module

        class DummyHandler:
            __module__ = module_name

            def do_POST(self):
                return None

        install_phase4_runtime(DummyHandler)
        return module

    def tearDown(self):
        for attr in ("grounding", "tool_defs", "tool_choice"):
            if hasattr(_state, attr):
                delattr(_state, attr)
        sys.modules.pop("_phase6_fake_server", None)

    def test_required_repairs_text_into_tool_call(self):
        calls = []
        valid = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"sample.txt"}}\n@@END_TOOL_CALL@@'

        def generate(prompt, *_a, **_k):
            calls.append(prompt)
            return "plain answer" if len(calls) == 1 else valid

        module = self._install_with(generate)
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "required"
        result = module.generate("Read sample.txt")
        self.assertEqual(result, valid)
        self.assertEqual(len(calls), 2)

    def test_named_required_repairs_wrong_tool_to_requested_tool(self):
        calls = []
        wrong = '@@TOOL_CALL@@\n{"name":"search","arguments":{"query":"sample"}}\n@@END_TOOL_CALL@@'
        valid = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"sample.txt"}}\n@@END_TOOL_CALL@@'

        def generate(prompt, *_a, **_k):
            calls.append(prompt)
            return wrong if len(calls) == 1 else valid

        module = self._install_with(generate)
        _state.tool_defs = [READ_FILE, SEARCH]
        _state.tool_choice = {"type": "function", "function": {"name": "read_file"}}
        result = module.generate("Read sample.txt")
        self.assertEqual(result, valid)
        self.assertEqual(len(calls), 2)
        self.assertIn("read_file", calls[1])

    def test_none_repairs_upstream_tool_call_to_text(self):
        calls = []
        tool_call = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"x"}}\n@@END_TOOL_CALL@@'

        def generate(prompt, *_a, **_k):
            calls.append(prompt)
            return tool_call if len(calls) == 1 else "hello"

        module = self._install_with(generate)
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "none"
        result = module.generate("Say hello")
        self.assertEqual(result, "hello")
        self.assertEqual(len(calls), 2)
        self.assertIn("Do not emit any tool call", calls[1])

    def test_malformed_tool_call_gets_one_repair(self):
        calls = []
        malformed = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":}}\n@@END_TOOL_CALL@@'
        valid = '@@TOOL_CALL@@\n{"name":"read_file","arguments":{"path":"x"}}\n@@END_TOOL_CALL@@'

        def generate(prompt, *_a, **_k):
            calls.append(prompt)
            return malformed if len(calls) == 1 else valid

        module = self._install_with(generate)
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = "auto"
        result = module.generate("Read x")
        self.assertEqual(result, valid)
        self.assertEqual(len(calls), 2)

    def test_invalid_tool_choice_does_not_invent_intent(self):
        module = self._install_with(lambda *_a, **_k: "should not matter")
        _state.tool_defs = [READ_FILE]
        _state.tool_choice = {"type": "function", "function": {"name": "missing"}}
        with self.assertRaisesRegex(RuntimeError, "tool_call_recovery_failed: invalid_tool_schema"):
            module.generate("Do the user's task")

    def test_repair_is_bounded(self):
        calls = []
        invalid = '@@TOOL_CALL@@\n{"name":"search","arguments":{}}\n@@END_TOOL_CALL@@'

        def generate(prompt, *_a, **_k):
            calls.append(prompt)
            return invalid

        module = self._install_with(generate)
        _state.tool_defs = [SEARCH]
        _state.tool_choice = "required"
        with self.assertRaisesRegex(RuntimeError, "tool_call_recovery_failed"):
            module.generate("Search for alpha")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
