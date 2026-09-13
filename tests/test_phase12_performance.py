"""Phase 12 performance/stability regression tests."""
from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError

from gemini_web2api.config import CONFIG
from gemini_web2api.context import compact_messages
from gemini_web2api.feature_porting import coerce_tool_call_enums
from gemini_web2api.gemini import _is_retryable_error, _retry_policy, extract_response_text
from gemini_web2api.performance import RetryPolicy, percentile
from gemini_web2api.tool_schema import normalize_tool_definitions
from gemini_web2api.tools import build_tool_prompt


class Phase12PerformanceTests(unittest.TestCase):
    def test_retry_policy_is_bounded_and_deterministic(self):
        policy = RetryPolicy(attempts=5, base_delay_sec=2, backoff_multiplier=2, max_delay_sec=5)
        self.assertEqual([policy.delay_for_retry(i) for i in range(5)], [2, 4, 5, 5, 5])
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0.95), 4.8)

    def test_retry_policy_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            RetryPolicy(attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(backoff_multiplier=0.5)
        with self.assertRaises(ValueError):
            RetryPolicy(max_delay_sec=-1)

    def test_retry_classifier_avoids_deterministic_upstream_retries(self):
        self.assertTrue(_is_retryable_error(TimeoutError("timeout")))
        self.assertTrue(_is_retryable_error(URLError("temporary network failure")))
        self.assertTrue(_is_retryable_error(HTTPError("u", 503, "busy", {}, None)))
        self.assertTrue(_is_retryable_error(RuntimeError("Gemini upstream returned an empty response")))
        self.assertFalse(_is_retryable_error(RuntimeError("Gemini upstream rejected request: BardErrorInfo [42]")))

    def test_retry_policy_reads_runtime_configuration(self):
        original = {key: CONFIG[key] for key in (
            "retry_attempts", "retry_delay_sec", "retry_backoff_multiplier", "retry_max_delay_sec"
        )}
        try:
            CONFIG.update({
                "retry_attempts": 4,
                "retry_delay_sec": 1,
                "retry_backoff_multiplier": 3,
                "retry_max_delay_sec": 7,
            })
            policy = _retry_policy()
            self.assertEqual(policy.attempts, 4)
            self.assertEqual([policy.delay_for_retry(i) for i in range(4)], [1, 3, 7, 7])
        finally:
            CONFIG.update(original)

    def test_context_compaction_preserves_current_task_and_recent_tool_state(self):
        messages = [{"role": "system", "content": "contract"}]
        for index in range(40):
            messages.append({"role": "user", "content": f"old task {index}"})
            messages.append({"role": "assistant", "content": "planning"})
            messages.append({"role": "tool", "name": "read_file", "content": f"result-{index}"})
        messages.append({"role": "user", "content": "CURRENT TASK: inspect target.py"})
        compacted, meta = compact_messages(messages, 500)
        serialized = json.dumps(compacted)
        self.assertTrue(meta["compacted"])
        self.assertIn("CURRENT TASK: inspect target.py", serialized)
        self.assertIn("result-39", serialized)
        self.assertIn("ELIDED HISTORY", serialized)
        self.assertLessEqual(meta["elided_messages"], len(messages))

    def test_context_compaction_handles_long_session_repeatedly(self):
        messages = [{"role": "system", "content": "contract"}]
        for index in range(300):
            messages.extend([
                {"role": "user", "content": f"task-{index}"},
                {"role": "assistant", "content": f"step-{index}"},
                {"role": "tool", "content": f"observation-{index}"},
            ])
        current = messages
        for _ in range(20):
            current, meta = compact_messages(current, 4000)
            self.assertTrue(meta["chars"] >= 0)
            self.assertIn("ELIDED HISTORY", json.dumps(current))
        self.assertIn("observation-299", json.dumps(current))

    def test_context_compaction_is_safe_under_concurrency(self):
        messages = [{"role": "system", "content": "contract"}]
        messages.extend({"role": "tool", "content": f"result-{i}"} for i in range(100))

        def worker():
            return compact_messages(messages, 700)[1]

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: worker(), range(32)))
        self.assertTrue(all(item["compacted"] for item in results))
        self.assertEqual(len({item["elided_messages"] for item in results}), 1)

    def test_tool_prompt_compaction_preserves_callable_schema(self):
        tools = []
        for index in range(20):
            tools.append({
                "name": f"tool_{index}",
                "description": "A very long description " * 50,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["fast", "safe"], "description": "mode " * 40},
                        "path": {"type": "string", "description": "path " * 40},
                    },
                    "required": ["path"],
                },
            })
        normalized = normalize_tool_definitions(tools, max_chars=6000)
        prompt = build_tool_prompt(tools)
        self.assertLess(len(prompt), len(json.dumps(tools, ensure_ascii=False, indent=2)) + 1000)
        self.assertIn("tool_0", prompt)
        self.assertIn("tool_19", prompt)
        self.assertIn("required", json.dumps(normalized))
        self.assertIn('"enum":["fast","safe"]', prompt)

    def test_parser_fast_path_preserves_longest_response(self):
        payloads = []
        for text in ("short", "the final response", "the final response with more detail"):
            inner = [None, None, None, None, [[None, [text]]]]
            payloads.append(json.dumps([["wrb.fr", None, json.dumps(inner)]], separators=(",", ":")))
        raw = "noise line\n" + "\n".join(payloads)
        self.assertEqual(extract_response_text(raw), "the final response with more detail")

    def test_enum_coercion_does_not_mutate_unknown_values(self):
        calls = [{
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"mode": " UNKNOWN ", "path": "x"}),
            }
        }]
        defs = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["safe", "fast"]}}},
            },
        }]
        normalized, changes = coerce_tool_call_enums(calls, defs)
        self.assertEqual(changes, [])
        self.assertEqual(normalized, calls)


if __name__ == "__main__":
    unittest.main()
