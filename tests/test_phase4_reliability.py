import unittest

from gemini_web2api.context import compact_messages
from gemini_web2api.grounding import GroundingFacts
from gemini_web2api.observability import new_trace_id, request_summary, response_summary, safe_tool_names


class GroundingContractTests(unittest.TestCase):
    def test_missing_grounding_is_unknown_not_inferred(self):
        facts = GroundingFacts.from_request({"messages": []})
        self.assertFalse(facts.is_explicit)
        self.assertEqual(facts.to_prompt(), "")

    def test_explicit_absolute_and_relative_facts_are_preserved(self):
        facts = GroundingFacts.from_request({
            "metadata": {"grounding": {
                "requested_cwd": "/tmp/hermes-test",
                "runtime_cwd": "/tmp/hermes-test",
                "task_target": "sample.txt",
                "known_files": ["README.md", "sample.txt"],
                "open_files": ["sample.txt"],
                "last_tool_call": {"name": "read_file", "arguments": {"path": "sample.txt"}},
                "last_tool_result": {"status": "ok", "path": "sample.txt", "content": "alpha"},
            }}
        })
        self.assertEqual(facts.requested_cwd, "/tmp/hermes-test")
        self.assertEqual(facts.task_target, "sample.txt")
        self.assertIn("sample.txt", facts.to_prompt())
        self.assertIn("Do not invent filesystem facts", facts.to_prompt())

    def test_malformed_grounding_is_fail_closed(self):
        facts = GroundingFacts.from_request({"grounding": "guess me"})
        self.assertFalse(facts.is_explicit)


class ContextBudgetTests(unittest.TestCase):
    def test_recent_tool_state_and_task_survive(self):
        messages = [
            {"role": "system", "content": "contract"},
            {"role": "user", "content": "old task"},
            {"role": "assistant", "content": "old answer"},
            {"role": "tool", "name": "list_files", "content": "old files"},
            {"role": "user", "content": "irrelevant history " * 20},
            {"role": "assistant", "content": "thinking " * 20},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read_file", "arguments": "{}"}}], "content": ""},
            {"role": "tool", "name": "read_file", "content": "alpha beta gamma"},
            {"role": "user", "content": "read sample.txt"},
        ]
        compacted, meta = compact_messages(messages, 260)
        rendered = "\n".join(str(m) for m in compacted)
        self.assertTrue(meta["compacted"])
        self.assertIn("read sample.txt", rendered)
        self.assertIn("alpha beta gamma", rendered)
        self.assertIn("ELIDED HISTORY", rendered)

    def test_disabled_budget_is_lossless(self):
        messages = [{"role": "user", "content": "x" * 1000}]
        result, meta = compact_messages(messages, 0)
        self.assertEqual(result, messages)
        self.assertFalse(meta["compacted"])


class ObservabilityTests(unittest.TestCase):
    def test_trace_ids_are_unique_and_non_secret(self):
        a, b = new_trace_id(), new_trace_id()
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{16}$")

    def test_tool_names_exclude_arguments(self):
        calls = [{"function": {"name": "read_file", "arguments": "SECRET"}}]
        self.assertEqual(safe_tool_names(calls), ["read_file"])

    def test_lifecycle_summaries_contain_no_headers_or_bodies(self):
        start = request_summary("POST", "/v1/chat/completions?key=secret", "abc", 42)
        end = response_summary("abc", 200, 12, "gemini-3.1-pro", ["read_file"])
        self.assertNotIn("secret", str(start))
        self.assertNotIn("Authorization", str(start))
        self.assertNotIn("arguments", str(end))
        self.assertEqual(start["path"], "/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
