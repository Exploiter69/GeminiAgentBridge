import email.message
import urllib.error
import unittest
from unittest.mock import patch

from gemini_web2api import gemini
from gemini_web2api.backend import BackendRequest
from gemini_web2api.gemini import _is_retryable_error
from gemini_web2api.server import GeminiHandler


class RateLimitRegressionTests(unittest.TestCase):
    def _http_error(self, status, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)

        return urllib.error.HTTPError(
            "https://gemini.google.com/",
            status,
            "upstream",
            headers,
            None,
        )

    def test_429_is_not_retryable(self):
        error = self._http_error(429)
        self.assertFalse(_is_retryable_error(error))

    def test_429_with_retry_after_is_not_retryable(self):
        error = self._http_error(429, 30)
        self.assertFalse(_is_retryable_error(error))

    def test_5xx_remains_retryable(self):
        self.assertTrue(_is_retryable_error(self._http_error(500)))
        self.assertTrue(_is_retryable_error(self._http_error(503)))
        self.assertTrue(_is_retryable_error(self._http_error(504)))

    def test_408_and_425_remain_retryable(self):
        self.assertTrue(_is_retryable_error(self._http_error(408)))
        self.assertTrue(_is_retryable_error(self._http_error(425)))

    def test_rate_limit_maps_to_http_429(self):
        exc = self._http_error(429, 37)

        status, payload, headers = GeminiHandler._upstream_error_response(exc)

        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["type"], "rate_limit")
        self.assertEqual(payload["error"]["message"], "upstream rate limit")
        self.assertEqual(headers["Retry-After"], "37")

    def test_rate_limit_without_retry_after_has_no_fake_delay(self):
        exc = self._http_error(429)

        status, payload, headers = GeminiHandler._upstream_error_response(exc)

        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["type"], "rate_limit")
        self.assertNotIn("Retry-After", headers)

    def test_authentication_errors_are_not_presented_as_502(self):
        for status in (401, 403):
            with self.subTest(status=status):
                exc = self._http_error(status)

                mapped_status, payload, _ = (
                    GeminiHandler._upstream_error_response(exc)
                )

                self.assertEqual(mapped_status, status)
                self.assertEqual(
                    payload["error"]["type"],
                    "authentication_error",
                )

    def test_responses_rate_limit_is_mapped_before_stream_headers(self):
        exc = self._http_error(429, 19)

        status, payload, headers = GeminiHandler._upstream_error_response(exc)

        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["type"], "rate_limit")
        self.assertEqual(payload["error"]["message"], "upstream rate limit")
        self.assertEqual(headers["Retry-After"], "19")

    def test_stream_rate_limit_payload_is_safe(self):
        exc = self._http_error(429, 23)

        status, payload, headers = GeminiHandler._upstream_error_response(exc)

        serialized = str(payload)

        self.assertEqual(status, 429)
        self.assertEqual(headers["Retry-After"], "23")
        self.assertNotIn("https://gemini.google.com/", serialized)
        self.assertNotIn("upstream", serialized.lower().replace(
            "upstream rate limit", ""
        ))

    def test_legacy_stream_retry_does_not_duplicate_emitted_prefix(self):
        class FakeResponse:
            def __init__(self, chunks, error_after=False):
                self.chunks = iter(chunks)
                self.error_after = error_after

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                return None

            def iter_text(self):
                for chunk in self.chunks:
                    yield chunk
                if self.error_after:
                    raise ConnectionError("connection dropped")

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def stream(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(["prefix\n"], error_after=True)
                return FakeResponse(["prefix-suffix\n"])

        request = BackendRequest(
            prompt="hello",
            model=1,
            stream=True,
        )
        client = FakeClient()

        with patch.object(gemini, "HAS_HTTPX", True), \
             patch.object(gemini, "_get_httpx_client", return_value=client), \
             patch.object(gemini, "_reset_httpx_client"), \
             patch.object(
                 gemini,
                 "_retry_policy",
                 return_value=type(
                     "Policy",
                     (),
                     {
                         "attempts": 2,
                         "delay_for_retry": lambda self, attempt: 0,
                     },
                 )(),
             ), \
             patch.object(gemini, "_sleep_before_retry"), \
             patch.object(
                 gemini,
                 "_extract_texts_from_line",
                 side_effect=[["prefix"], ["prefix-suffix"]],
             ):
            emitted = list(gemini._legacy_stream(request))

        self.assertEqual(emitted, ["prefix", "-suffix"])
        self.assertEqual(client.calls, 2)

    def test_unknown_upstream_errors_remain_502(self):
        status, payload, headers = (
            GeminiHandler._upstream_error_response(
                RuntimeError("transport failure")
            )
        )

        self.assertEqual(status, 502)
        self.assertEqual(payload["error"]["type"], "upstream_error")
        self.assertEqual(headers, {})


if __name__ == "__main__":
    unittest.main()
