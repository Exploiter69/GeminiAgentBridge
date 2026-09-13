import json
import threading
import unittest

from gemini_web2api.observability import (
    EVENT_NAMES,
    TraceRecorder,
    clear_trace_events,
    emit_event,
    event_json,
    get_trace_events,
    make_event,
    new_trace_id,
    request_summary,
    response_summary,
    safe_path,
    safe_tool_names,
    sanitize_event,
)


class Phase10ObservabilityTests(unittest.TestCase):
    def setUp(self):
        clear_trace_events()

    def tearDown(self):
        clear_trace_events()

    def test_all_canonical_events_are_accepted(self):
        trace = new_trace_id()
        events = [make_event(trace, name) for name in EVENT_NAMES]
        self.assertEqual([event["event"] for event in events], list(EVENT_NAMES))
        self.assertTrue(all(event["trace_id"] == trace for event in events))

    def test_unknown_event_is_rejected(self):
        with self.assertRaises(ValueError):
            make_event(new_trace_id(), "made_up_event")

    def test_trace_is_unique_and_safe(self):
        values = {new_trace_id() for _ in range(1000)}
        self.assertEqual(len(values), 1000)
        self.assertTrue(all(len(value) == 16 for value in values))
        self.assertTrue(all(value.isascii() and all(c in "0123456789abcdef" for c in value) for value in values))

    def test_tool_arguments_and_content_never_enter_event(self):
        trace = new_trace_id()
        event = make_event(
            trace,
            "candidate_tool_call",
            tool_names=["read_file"],
            arguments="SUPER_SECRET_ARGUMENT",
            authorization="SECRET_HEADER_VALUE",
            cookie="session=SUPER_SECRET",
            response="PRIVATE_CONTENT",
        )
        encoded = event_json(event)
        self.assertNotIn("SUPER_SECRET", encoded)
        self.assertNotIn("PRIVATE_CONTENT", encoded)
        self.assertIn("[REDACTED]", encoded)
        self.assertIn("read_file", encoded)

    def test_query_string_is_redacted_before_logging(self):
        self.assertEqual(safe_path("/v1/models?key=secret&x=1"), "/v1/models?key=[REDACTED]&x=1")
        start = request_summary("GET", "/v1/models?access_token=secret", "abc123", 0)
        self.assertNotIn("secret", str(start))
        self.assertEqual(start["path"], "/v1/models")

    def test_safe_tool_names_excludes_arguments(self):
        calls = [
            {"function": {"name": "read_file", "arguments": "TOP_SECRET"}},
            {"name": "search", "arguments": {"query": "PRIVATE"}},
        ]
        self.assertEqual(safe_tool_names(calls), ["read_file", "search"])

    def test_recorder_is_bounded_and_filterable(self):
        recorder = TraceRecorder(max_events=3)
        first = new_trace_id()
        second = new_trace_id()
        for index in range(5):
            recorder.record(make_event(first if index < 4 else second, "next_turn", index=index))
        self.assertEqual(len(recorder.snapshot()), 3)
        self.assertEqual(len(recorder.snapshot(first)), 2)
        self.assertEqual(len(recorder.snapshot(second)), 1)

    def test_global_events_preserve_one_trace(self):
        trace = new_trace_id()
        emit_event(trace, "request_received", method="POST")
        emit_event(trace, "context_built", message_count=2)
        emit_event(trace, "request_completed", status=200)
        events = get_trace_events(trace)
        self.assertEqual([e["event"] for e in events], ["request_received", "context_built", "request_completed"])
        self.assertTrue(all(e["trace_id"] == trace for e in events))

    def test_concurrent_recording_does_not_lose_events(self):
        recorder = TraceRecorder(max_events=1000)
        traces = [new_trace_id() for _ in range(10)]

        def worker(trace):
            for index in range(50):
                recorder.record(make_event(trace, "next_turn", index=index))

        threads = [threading.Thread(target=worker, args=(trace,)) for trace in traces]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(recorder.snapshot()), 500)
        for trace in traces:
            self.assertEqual(len(recorder.snapshot(trace)), 50)

    def test_response_summary_remains_backward_compatible_and_safe(self):
        event = response_summary("abc", 502, 17, "gemini", ["read_file"])
        self.assertEqual(event["status"], 502)
        self.assertEqual(event["tool_names"], ["read_file"])
        self.assertNotIn("arguments", event)

    def test_sanitize_event_handles_nested_secret_keys(self):
        value = sanitize_event({
            "metadata": {"authorization": "secret", "safe": "ok"},
            "tools": [{"name": "read_file", "token": "secret"}],
        })
        encoded = json.dumps(value)
        self.assertNotIn("secret", encoded)
        self.assertIn("ok", encoded)
        self.assertIn("[REDACTED]", encoded)


if __name__ == "__main__":
    unittest.main()
