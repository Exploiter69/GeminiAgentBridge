import email.message
import urllib.error
import unittest

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
