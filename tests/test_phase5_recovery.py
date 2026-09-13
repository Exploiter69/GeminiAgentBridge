import socket
import sys
import types
import unittest
import urllib.error

from gemini_web2api.recovery import (
    ErrorType,
    classify_exception,
    classify_http_status,
    classify_tool_validation,
    classify_upstream_text,
    failed_tool_observation,
    is_failed_tool_observation,
    preserve_tool_observation,
    retry_delay,
    run_with_recovery,
)
from gemini_web2api.phase4_runtime import install_phase4_runtime


class ClassificationTests(unittest.TestCase):
    def test_http_classification(self):
        self.assertEqual(classify_http_status(408), ErrorType.TIMEOUT)
        self.assertEqual(classify_http_status(429), ErrorType.RATE_LIMIT)
        self.assertEqual(classify_http_status(401), ErrorType.AUTHENTICATION)
        self.assertEqual(classify_http_status(403), ErrorType.AUTHENTICATION)
        self.assertEqual(classify_http_status(503), ErrorType.SESSION)
        self.assertEqual(classify_http_status(504), ErrorType.TIMEOUT)

    def test_timeout_exception_is_retryable(self):
        failure = classify_exception(socket.timeout())
        self.assertEqual(failure.error_type, ErrorType.TIMEOUT)
        self.assertTrue(failure.retryable)

    def test_http_auth_is_not_retryable(self):
        exc = urllib.error.HTTPError("https://example.invalid", 401, "unauthorized", {}, None)
        failure = classify_exception(exc)
        self.assertEqual(failure.error_type, ErrorType.AUTHENTICATION)
        self.assertFalse(failure.retryable)

    def test_bard_rate_limit_is_retryable(self):
        failure = classify_exception(RuntimeError("Gemini upstream rejected request: BardErrorInfo [429]"))
        self.assertEqual(failure.error_type, ErrorType.RATE_LIMIT)
        self.assertTrue(failure.retryable)

    def test_bard_auth_failure_is_not_retryable(self):
        failure = classify_exception(RuntimeError("Gemini upstream rejected request: BardErrorInfo [401]"))
        self.assertEqual(failure.error_type, ErrorType.AUTHENTICATION)
        self.assertFalse(failure.retryable)

    def test_upstream_text_classification_does_not_expose_raw_text(self):
        failure = classify_upstream_text("BardErrorInfo [429] secret-cookie-value")
        self.assertIsNotNone(failure)
        self.assertEqual(failure.error_type, ErrorType.RATE_LIMIT)
        self.assertNotIn("secret-cookie-value", failure.message)

    def test_empty_response_is_classified(self):
        failure = classify_upstream_text("   ")
        self.assertEqual(failure.error_type, ErrorType.EMPTY_RESPONSE)
        self.assertTrue(failure.retryable)

    def test_tool_validation_failures_are_repairable(self):
        malformed = classify_tool_validation(["tool_calls[0].arguments: invalid JSON"])
        missing = classify_tool_validation(["tool_calls[0].arguments.path: required field is missing"])
        schema = classify_tool_validation(["tool_calls[0].arguments.mode: value is not allowed"])
        self.assertEqual(malformed.error_type, ErrorType.MALFORMED_TOOL_CALL)
        self.assertEqual(missing.error_type, ErrorType.MISSING_REQUIRED_ARGUMENT)
        self.assertEqual(schema.error_type, ErrorType.INVALID_TOOL_SCHEMA)
        self.assertTrue(malformed.repairable)
        self.assertTrue(missing.repairable)
        self.assertTrue(schema.repairable)


class RetryTests(unittest.TestCase):
    def test_retry_is_bounded_and_eventually_succeeds(self):
        calls = []
        sleeps = []

        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise TimeoutError("temporary")
            return "ok"

        result = run_with_recovery(operation, 3, 0.1, sleeper=sleeps.append)
        self.assertTrue(result.ok)
        self.assertEqual(result.value, "ok")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps, [0.1, 0.2])

    def test_non_retryable_error_stops_immediately(self):
        calls = []

        def operation():
            calls.append(1)
            raise urllib.error.HTTPError("https://example.invalid", 401, "unauthorized", {}, None)

        result = run_with_recovery(operation, 5, 0, sleeper=lambda _: self.fail("must not sleep"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.error_type, ErrorType.AUTHENTICATION)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(calls), 1)

    def test_attempt_count_never_exceeds_configured_bound(self):
        calls = []

        def operation():
            calls.append(1)
            raise TimeoutError("temporary")

        result = run_with_recovery(operation, 2, 0, sleeper=lambda _: None)
        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(calls), 2)

    def test_backoff_is_capped(self):
        self.assertEqual(retry_delay(10, 1, cap=30), 10)
        self.assertEqual(retry_delay(10, 2, cap=30), 20)
        self.assertEqual(retry_delay(10, 3, cap=30), 30)
        self.assertEqual(retry_delay(10, 1, retry_after=60, cap=30), 30)


class RuntimeIntegrationTests(unittest.TestCase):
    def _install_with(self, generate):
        module_name = "_phase5_fake_server"
        module = types.ModuleType(module_name)
        module.generate = generate
        module.log = lambda _msg: None
        sys.modules[module_name] = module

        class DummyHandler:
            __module__ = module_name

            def do_POST(self):
                return None

        install_phase4_runtime(DummyHandler)
        return module, DummyHandler

    def tearDown(self):
        sys.modules.pop("_phase5_fake_server", None)

    def test_runtime_wraps_actual_modular_generate(self):
        module, _ = self._install_with(lambda *_a, **_k: "")
        with self.assertRaisesRegex(RuntimeError, "upstream empty_response"):
            module.generate("prompt")

    def test_runtime_sanitizes_timeout_error(self):
        def fail(*_a, **_k):
            raise TimeoutError("secret-cookie-value")

        module, _ = self._install_with(fail)
        with self.assertRaisesRegex(RuntimeError, "upstream timeout") as ctx:
            module.generate("prompt")
        self.assertNotIn("secret-cookie-value", str(ctx.exception))

    def test_runtime_classifies_bard_rate_limit(self):
        module, _ = self._install_with(lambda *_a, **_k: "BardErrorInfo [429]")
        with self.assertRaisesRegex(RuntimeError, "upstream rate_limit"):
            module.generate("prompt")


class ToolObservationTests(unittest.TestCase):
    def test_failed_observation_is_explicit_error(self):
        result = failed_tool_observation(
            "read_file", ErrorType.TOOL_RESULT_ERROR, "file not found", path="/requested/path"
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "tool_result_error")
        self.assertEqual(result["path"], "/requested/path")
        self.assertTrue(is_failed_tool_observation(result))

    def test_failed_observation_is_not_rewritten_as_success(self):
        result = failed_tool_observation("read_file", "file_not_found", "missing", path="x")
        preserved = preserve_tool_observation(result)
        self.assertEqual(preserved, result)
        self.assertEqual(preserved["status"], "error")

    def test_legitimate_empty_result_is_not_invented_as_failure(self):
        empty = {"status": "success", "files": []}
        self.assertFalse(is_failed_tool_observation(empty))
        self.assertEqual(preserve_tool_observation(empty), empty)


if __name__ == "__main__":
    unittest.main()
