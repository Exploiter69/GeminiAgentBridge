import asyncio
import queue
import unittest

from gemini_web2api.backend import BackendCapabilities, BackendCapabilityError, BackendRequest
from gemini_web2api.modern import _ModernBackend


class ReasoningCapabilityTests(unittest.TestCase):
    def _backend_with(self, client):
        backend = _ModernBackend.__new__(_ModernBackend)
        backend._async_lock = asyncio.Lock()

        async def ensure_client():
            return client

        backend._ensure_client = ensure_client
        return backend

    def test_modern_generation_preserves_upstream_thoughts(self):
        class Response:
            text = "final answer"
            thoughts = "internal reasoning"

        class Client:
            async def generate_content(self, prompt, **kwargs):
                return Response()

        backend = self._backend_with(Client())
        response = asyncio.run(
            backend._generate_once(
                BackendRequest(prompt="solve", model="gemini-test")
            )
        )

        self.assertEqual(response.text, "final answer")
        self.assertEqual(response.thoughts, "internal reasoning")

    def test_modern_generation_keeps_empty_thoughts_empty(self):
        class Response:
            text = "final answer"
            thoughts = None

        class Client:
            async def generate_content(self, prompt, **kwargs):
                return Response()

        backend = self._backend_with(Client())
        response = asyncio.run(
            backend._generate_once(
                BackendRequest(prompt="solve", model="gemini-test")
            )
        )

        self.assertEqual(response.thoughts, "")
        self.assertFalse(hasattr(response, "reasoning_content"))

    def test_modern_stream_keeps_thoughts_out_of_text_output(self):
        class Chunk:
            def __init__(self, text_delta=None, thoughts_delta=None):
                self.text_delta = text_delta
                self.thoughts_delta = thoughts_delta

        class Client:
            async def generate_content_stream(self, prompt, **kwargs):
                yield Chunk(thoughts_delta="internal reasoning")
                yield Chunk(text_delta="final answer")

        backend = self._backend_with(Client())
        out = queue.Queue()
        state = {"error": None, "emitted": False, "thoughts_delta": ""}

        asyncio.run(
            backend._stream_once(
                BackendRequest(prompt="solve", model="gemini-test", stream=True),
                out,
                state,
            )
        )

        self.assertEqual(state["thoughts_delta"], "internal reasoning")
        self.assertTrue(state["emitted"])
        self.assertEqual(out.get_nowait(), "final answer")
        self.assertTrue(out.empty())

    def test_modern_numeric_think_override_is_explicitly_rejected(self):
        backend = _ModernBackend.__new__(_ModernBackend)
        request = BackendRequest(
            prompt="solve",
            model="gemini-test",
            think_mode=4,
        )

        with self.assertRaisesRegex(BackendCapabilityError, "numeric think level"):
            backend._kwargs(object(), request, [])

    def test_modern_thought_capability_is_declared(self):
        self.assertIsInstance(_ModernBackend.capabilities, BackendCapabilities)
        self.assertTrue(_ModernBackend.capabilities.thoughts)
        self.assertTrue(_ModernBackend.capabilities.streaming)

    def test_backend_response_has_no_fabricated_reasoning_field(self):
        class Response:
            text = "final answer"
            thoughts = "provider reasoning"

        class Client:
            async def generate_content(self, prompt, **kwargs):
                return Response()

        backend = self._backend_with(Client())
        response = asyncio.run(
            backend._generate_once(
                BackendRequest(prompt="solve", model="gemini-test")
            )
        )

        self.assertEqual(response.thoughts, "provider reasoning")
        self.assertFalse(hasattr(response, "reasoning_content"))
        self.assertNotIn("reasoning_content", response.__dict__)


if __name__ == "__main__":
    unittest.main()
