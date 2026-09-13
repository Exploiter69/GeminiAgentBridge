import os
import tempfile
import unittest
from unittest.mock import patch

from gemini_web2api import modern
from gemini_web2api.config import CONFIG


class FailingAfterOutputClient:
    instances = []

    def __init__(self, psid, psidts, proxy=None):
        self.calls = 0
        self.closed = False
        self.__class__.instances.append(self)

    async def init(self, **kwargs):
        return None

    async def close(self):
        self.closed = True

    async def generate_content_stream(self, prompt, **kwargs):
        self.calls += 1
        yield type("Chunk", (), {"text_delta": "tool-prefix"})()
        raise RuntimeError("transport broke after output")


class ModernSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original = dict(CONFIG)
        FailingAfterOutputClient.instances.clear()
        modern._BACKEND.shutdown()
        modern._BACKEND = modern._ModernBackend()

    def tearDown(self):
        modern._BACKEND.shutdown()
        CONFIG.clear()
        CONFIG.update(self.original)

    def test_stream_failure_after_output_is_not_retried(self):
        CONFIG["retry_attempts"] = 3
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("__Secure-1PSID=psid-value; __Secure-1PSIDTS=psidts-value")
            path = handle.name
        try:
            CONFIG["cookie_file"] = path
            with patch.object(modern, "GeminiClient", FailingAfterOutputClient):
                stream = modern._BACKEND.generate_stream("hello", 1)
                self.assertEqual(next(stream), "tool-prefix")
                with self.assertRaises(RuntimeError):
                    next(stream)
            self.assertEqual(FailingAfterOutputClient.instances[-1].calls, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
