import os
import tempfile
import unittest
from unittest.mock import patch

from gemini_web2api import gemini, modern
from gemini_web2api.backend import BackendFile, BackendRequest, BackendResponse
from gemini_web2api.config import CONFIG


class FakeResponse:
    text = "modern response"
    thoughts = "internal thoughts"


class FakeClient:
    instances = []

    def __init__(self, psid, psidts, proxy=None):
        self.psid = psid
        self.psidts = psidts
        self.proxy = proxy
        self.closed = False
        self.initialized = False
        self.calls = []
        self.file_snapshots = []
        self.__class__.instances.append(self)

    async def init(self, **kwargs):
        self.initialized = True
        self.init_kwargs = kwargs

    async def close(self):
        self.closed = True

    def resolve_model(self, name):
        return f"resolved:{name}"

    def list_models(self):
        return [type("Model", (), {"model_name": "gemini-flash", "display_name": "Flash", "is_available": True})()]

    async def generate_content(self, prompt, **kwargs):
        self.calls.append(("generate", prompt, kwargs))
        for path in kwargs.get("files", []):
            with open(path, "rb") as handle:
                self.file_snapshots.append(handle.read())
        return FakeResponse()

    async def generate_content_stream(self, prompt, **kwargs):
        self.calls.append(("stream", prompt, kwargs))
        for value in ("modern ", "stream"):
            yield type("Chunk", (), {"text_delta": value, "thoughts_delta": None})()


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

    def _cookie_file(self):
        handle = tempfile.NamedTemporaryFile("w", delete=False)
        handle.write("__Secure-1PSID=psid-value; __Secure-1PSIDTS=psidts-value")
        handle.close()
        return handle.name

    def test_cookie_values_are_read_without_logging_contents(self):
        path = self._cookie_file()
        try:
            CONFIG["cookie_file"] = path
            self.assertEqual(modern._BACKEND._cookie_values(), ("psid-value", "psidts-value"))
        finally:
            os.unlink(path)

    def test_modern_preserves_model_files_temporary_and_thoughts(self):
        path = self._cookie_file()
        try:
            CONFIG["cookie_file"] = path
            with patch.object(modern, "GeminiClient", FakeClient):
                request = BackendRequest(prompt="inspect image", model="gemini-3.6-flash", files=(BackendFile(b"PNGDATA", "image/png", "photo.png"),), temporary=True)
                result = modern._BACKEND.generate_response(request)
            self.assertIsInstance(result, BackendResponse)
            self.assertEqual(result.text, "modern response")
            self.assertEqual(result.thoughts, "internal thoughts")
            client = FakeClient.instances[-1]
            kwargs = client.calls[0][2]
            self.assertEqual(kwargs["model"], "resolved:gemini-3.6-flash")
            self.assertTrue(kwargs["temporary"])
            self.assertEqual(len(kwargs["files"]), 1)
            self.assertEqual(client.file_snapshots, [b"PNGDATA"])
            self.assertFalse(os.path.exists(kwargs["files"][0]))
        finally:
            os.unlink(path)

    def test_modern_stream_yields_only_text_deltas(self):
        path = self._cookie_file()
        try:
            CONFIG["cookie_file"] = path
            with patch.object(modern, "GeminiClient", FakeClient):
                result = list(modern._BACKEND.generate_stream("hello", 1))
            self.assertEqual(result, ["modern ", "stream"])
        finally:
            os.unlink(path)

    def test_generate_routes_complete_request_to_modern(self):
        CONFIG["upstream_backend"] = "modern"
        expected = BackendResponse("modern")
        with patch.object(gemini, "modern_generate_response", return_value=expected) as modern_call:
            result = gemini.generate("hello", "gemini-3.6-flash", None, [], None)
        self.assertEqual(result, "modern")
        request = modern_call.call_args.args[0]
        self.assertIsInstance(request, BackendRequest)
        self.assertEqual(request.model, "gemini-3.6-flash")


if __name__ == "__main__":
    unittest.main()
