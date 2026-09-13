import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gemini_web2api import gemini, modern
from gemini_web2api.config import CONFIG


class FakeResponse:
    text = "modern response"


class FakeClient:
    instances = []

    def __init__(self, psid, psidts, proxy=None):
        self.psid = psid
        self.psidts = psidts
        self.proxy = proxy
        self.closed = False
        self.initialized = False
        self.calls = []
        self.__class__.instances.append(self)

    async def init(self, **kwargs):
        self.initialized = True
        self.init_kwargs = kwargs

    async def close(self):
        self.closed = True

    async def generate_content(self, prompt, **kwargs):
        self.calls.append(("generate", prompt, kwargs))
        return FakeResponse()

    async def generate_content_stream(self, prompt, **kwargs):
        self.calls.append(("stream", prompt, kwargs))
        for value in ("modern ", "stream"):
            yield type("Chunk", (), {"text_delta": value})()


class ModernTransportTests(unittest.TestCase):
    def setUp(self):
        self.original = dict(CONFIG)
        FakeClient.instances.clear()
        modern._BACKEND.shutdown()
        modern._BACKEND = modern._ModernBackend()

    def tearDown(self):
        modern._BACKEND.shutdown()
        CONFIG.clear()
        CONFIG.update(self.original)

    def test_cookie_values_are_read_without_logging_contents(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            json.dump({"cookie": "__Secure-1PSID=psid-value; __Secure-1PSIDTS=psidts-value"}, handle)
            path = handle.name
        try:
            CONFIG["cookie_file"] = path
            self.assertEqual(modern._BACKEND._cookie_values(), ("psid-value", "psidts-value"))
        finally:
            os.unlink(path)

    def test_modern_client_uses_dynamic_model_tier(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("__Secure-1PSID=psid-value; __Secure-1PSIDTS=psidts-value")
            path = handle.name
        try:
            CONFIG["cookie_file"] = path
            with patch.object(modern, "GeminiClient", FakeClient):
                result = modern._BACKEND.generate("hello", 3)
            self.assertEqual(result, "modern response")
            client = FakeClient.instances[-1]
            self.assertTrue(client.initialized)
            self.assertEqual(client.calls[0][2]["model"], "gemini-pro")
        finally:
            os.unlink(path)

    def test_modern_stream_yields_only_text_deltas(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("__Secure-1PSID=psid-value; __Secure-1PSIDTS=psidts-value")
            path = handle.name
        try:
            CONFIG["cookie_file"] = path
            with patch.object(modern, "GeminiClient", FakeClient):
                result = list(modern._BACKEND.generate_stream("hello", 1))
            self.assertEqual(result, ["modern ", "stream"])
        finally:
            os.unlink(path)

    def test_generate_routes_to_modern_by_default(self):
        CONFIG["upstream_backend"] = "modern"
        with patch.object(gemini, "modern_generate", return_value="modern") as modern_call:
            result = gemini.generate("hello", 1, 4)
        self.assertEqual(result, "modern")
        modern_call.assert_called_once_with("hello", 1)


if __name__ == "__main__":
    unittest.main()
