import json
import unittest

from gemini_web2api.response_semantics import remove_fabricated_usage, sanitize_sse_event


class ResponseSemanticsTests(unittest.TestCase):
    def test_usage_is_removed_without_changing_other_fields(self):
        payload = {
            "id": "resp_test",
            "model": "gemini",
            "usage": {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}],
        }
        sanitized = remove_fabricated_usage(payload)
        self.assertNotIn("usage", sanitized)
        self.assertEqual(sanitized["output"][0]["content"][0]["text"], "hello")

    def test_nested_usage_is_removed(self):
        sanitized = remove_fabricated_usage({"response": {"usage": {"total_tokens": 1}, "ok": True}})
        self.assertEqual(sanitized, {"response": {"ok": True}})

    def test_sse_usage_is_removed_and_done_is_preserved(self):
        event = (
            b"event: response.completed\n"
            b'data: {"type":"response.completed","response":{"status":"completed","usage":{"total_tokens":99}}}\n\n'
            b"data: [DONE]\n\n"
        )
        output = sanitize_sse_event(event).decode()
        self.assertNotIn('"usage"', output)
        self.assertIn('"status":"completed"', output)
        self.assertIn("data: [DONE]", output)

    def test_sse_non_json_lines_are_untouched(self):
        output = sanitize_sse_event(b": heartbeat\n\ndata: [DONE]\n\n").decode()
        self.assertIn(": heartbeat", output)
        self.assertIn("data: [DONE]", output)


if __name__ == "__main__":
    unittest.main()
