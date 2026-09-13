import io
import unittest
from unittest.mock import patch

from gemini_web2api.config import CONFIG
from gemini_web2api.hardened_server import HardenedGeminiHandler
from gemini_web2api.multimodal import _resolve_public_host, _validate_remote_url
from gemini_web2api.security import RequestBodyTooLarge, validate_bind


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


if __name__ == "__main__":
    unittest.main()
