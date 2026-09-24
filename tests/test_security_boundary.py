import io
import unittest
from unittest.mock import patch

from gemini_web2api.config import CONFIG
from gemini_web2api.hardened_server import HardenedGeminiHandler
from gemini_web2api.multimodal import _resolve_public_host, _validate_remote_url
from gemini_web2api.security import RequestBodyTooLarge, validate_bind
from gemini_web2api import server


class SecurityBoundaryTests(unittest.TestCase):
    def test_default_bind_policy_allows_loopback(self):
        validate_bind("127.0.0.1", [])
        validate_bind("localhost", [])

    def test_remote_bind_requires_key(self):
        with self.assertRaises(ValueError):
            validate_bind("0.0.0.0", [])
        validate_bind("0.0.0.0", ["test-key"])

    def test_ssrf_blocks_private_and_loopback_targets(self):
        for host in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.1.1", "::1"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    _resolve_public_host(host)

    def test_ssrf_rejects_non_http_and_credentials(self):
        with self.assertRaises(ValueError):
            _validate_remote_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            _validate_remote_url("https://user:pass@example.com/image.png")

    def test_content_length_limit_is_enforced_before_read(self):
        handler = object.__new__(HardenedGeminiHandler)
        handler.headers = {"Content-Length": "11"}
        handler.rfile = io.BytesIO(b"hello world")
        old = CONFIG["max_request_body_bytes"]
        CONFIG["max_request_body_bytes"] = 10
        try:
            with self.assertRaises(RequestBodyTooLarge):
                handler._read_request_body()
        finally:
            CONFIG["max_request_body_bytes"] = old

    def test_chunked_limit_is_enforced(self):
        handler = object.__new__(HardenedGeminiHandler)
        handler.headers = {"Transfer-Encoding": "chunked"}
        handler.rfile = io.BytesIO(b"b\r\nhello world\r\n0\r\n\r\n")
        old = CONFIG["max_request_body_bytes"]
        CONFIG["max_request_body_bytes"] = 10
        try:
            with self.assertRaises(RequestBodyTooLarge):
                handler._read_request_body()
        finally:
            CONFIG["max_request_body_bytes"] = old

    def test_do_post_catchall_never_echoes_or_logs_raw_exception_text(self):
        # Regression: the legacy GeminiHandler.do_POST outer catch-all used to
        # log and return str(exc) verbatim to the calling HTTP client. Since
        # urllib HTTPError/URLError string forms can embed the outgoing
        # Gemini request URL (which carries the session XSRF token as a query
        # parameter), any exception reaching this last-resort boundary must
        # be reported generically, not echoed back. hardened_server.py's
        # equivalent boundary already does this correctly; this pins the
        # legacy server.py boundary to the same behavior.
        handler = object.__new__(server.GeminiHandler)
        handler.path = "/v1/chat/completions"
        handler.client_address = ("127.0.0.1", 12345)

        secret = "at=SUPER-SECRET-XSRF-TOKEN-abc123"
        recorded = {}

        def fake_send_json(data, status=200):
            recorded["data"] = data
            recorded["status"] = status

        handler.send_json = fake_send_json

        old_keys = CONFIG.get("api_keys")
        CONFIG["api_keys"] = []
        try:
            with patch.object(server.GeminiHandler, "_read_request_body", side_effect=RuntimeError(f"boom {secret}")), \
                 patch.object(server, "log") as mock_log:
                handler.do_POST()
        finally:
            CONFIG["api_keys"] = old_keys

        self.assertEqual(recorded["status"], 500)
        serialized = str(recorded["data"])
        self.assertNotIn(secret, serialized)
        self.assertNotIn("SUPER-SECRET", serialized)

        logged = " ".join(str(c) for c in mock_log.call_args_list)
        self.assertNotIn(secret, logged)
        self.assertNotIn("SUPER-SECRET", logged)


if __name__ == "__main__":
    unittest.main()
