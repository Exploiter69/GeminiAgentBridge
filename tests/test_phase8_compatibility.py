import unittest

from gemini_web2api.client_compat import (
    COMPATIBILITY_MATRIX,
    case_names,
    validate_chat_completion,
    validate_models_response,
)


class Phase8MatrixTests(unittest.TestCase):
    def test_matrix_contains_required_hermes_opencode_tasks(self):
        required = {
            "list_files", "read_file", "create_file", "edit_file", "terminal",
            "search_then_read", "search_then_edit", "multi_step", "test_execution",
            "git_status", "git_diff", "explicit_workdir", "long_task",
        }
        self.assertTrue(required.issubset(set(case_names())))
        self.assertEqual(len(COMPATIBILITY_MATRIX), len(set(case_names())))

    def test_every_case_has_prompt_and_tool_contract(self):
        for case in COMPATIBILITY_MATRIX:
            self.assertTrue(case.prompt)
            self.assertTrue(case.required_tools)


class Phase8ProtocolTests(unittest.TestCase):
    def test_valid_text_completion(self):
        payload = {
            "object": "chat.completion",
            "choices": [{
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }],
        }
        self.assertEqual(validate_chat_completion(payload), [])

    def test_valid_tool_completion(self):
        payload = {
            "object": "chat.completion",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_test",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"sample.txt"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        self.assertEqual(validate_chat_completion(payload), [])

    def test_invalid_tool_completion_is_rejected(self):
        payload = {
            "object": "chat.completion",
            "choices": [{
                "message": {"role": "assistant", "content": None},
                "finish_reason": "tool_calls",
            }],
        }
        self.assertIn("tool_calls finish without tool_calls", validate_chat_completion(payload))

    def test_models_response_contract(self):
        self.assertEqual(validate_models_response({
            "object": "list",
            "data": [{"id": "gemini-3.6-flash"}],
        }), [])

    def test_models_response_rejects_empty_catalog(self):
        self.assertTrue(validate_models_response({"object": "list", "data": []}))


if __name__ == "__main__":
    unittest.main()
