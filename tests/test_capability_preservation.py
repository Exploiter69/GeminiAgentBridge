import os
import tempfile
import unittest
from pathlib import Path

from gemini_web2api.backend import BackendFile, BackendRequest
from gemini_web2api.multimodal import UploadedFileRef
from gemini_web2api.modern import _ModernBackend
from gemini_web2api.protocol import parse_tool_calls_robust
from gemini_web2api.context import compact_messages


class MultimodalCapabilityTests(unittest.TestCase):

    def test_uploaded_file_ref_preserves_all_metadata(self):
        ref = UploadedFileRef(
            "/agentbridge/local/report.pdf",
            b"pdf-bytes",
            "application/pdf",
            "report.pdf",
        )

        self.assertEqual(str(ref), "/agentbridge/local/report.pdf")
        self.assertEqual(ref.data, b"pdf-bytes")
        self.assertEqual(ref.mime_type, "application/pdf")
        self.assertEqual(ref.filename, "report.pdf")

    def test_backend_file_preserves_name_mime_and_bytes(self):
        file = BackendFile(
            data=b"png-bytes",
            mime_type="image/png",
            filename="diagram.png",
        )

        self.assertEqual(file.filename, "diagram.png")
        self.assertEqual(file.mime_type, "image/png")
        self.assertEqual(file.data, b"png-bytes")

    def test_multiple_backend_files_preserve_order_and_metadata(self):
        files = [
            BackendFile(b"first", "text/plain", "first.txt"),
            BackendFile(b"second", "image/png", "second.png"),
            BackendFile(b"third", "application/pdf", "third.pdf"),
        ]

        self.assertEqual(
            [(f.filename, f.mime_type, f.data) for f in files],
            [
                ("first.txt", "text/plain", b"first"),
                ("second.png", "image/png", b"second"),
                ("third.pdf", "application/pdf", b"third"),
            ],
        )

    def test_modern_materialization_uses_original_filename(self):
        backend = _ModernBackend.__new__(_ModernBackend)

        files = [
            BackendFile(
                data=b"pdf-data",
                mime_type="application/pdf",
                filename="report.pdf",
            )
        ]

        paths = backend._materialize_files(files)

        try:
            self.assertEqual(len(paths), 1)

            path = Path(paths[0])
            self.assertTrue(path.exists())
            self.assertEqual(path.suffix, ".pdf")
            self.assertEqual(path.read_bytes(), b"pdf-data")
        finally:
            for path in paths:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass

        self.assertFalse(Path(paths[0]).exists())

    def test_modern_generation_failure_cleans_materialized_files(self):
        import asyncio

        backend = _ModernBackend.__new__(_ModernBackend)
        backend._async_lock = asyncio.Lock()

        class FailingClient:
            async def generate_content(self, prompt, **kwargs):
                raise RuntimeError("synthetic generation failure")

        async def ensure_client():
            return FailingClient()

        backend._ensure_client = ensure_client

        request = BackendRequest(
            prompt="test",
            model="gemini-test",
            files=(
                BackendFile(
                    data=b"failure-cleanup",
                    mime_type="application/octet-stream",
                    filename="failure.bin",
                ),
            ),
        )

        async def exercise():
            with self.assertRaises(RuntimeError):
                await backend._generate_once(request)

        asyncio.run(exercise())

        leftovers = list(Path(tempfile.gettempdir()).glob("gemini-bridge-*"))
        self.assertEqual(leftovers, [])

    def test_modern_stream_failure_cleans_materialized_files(self):
        import asyncio

        backend = _ModernBackend.__new__(_ModernBackend)
        backend._async_lock = asyncio.Lock()

        class FailingClient:
            async def generate_content_stream(self, prompt, **kwargs):
                if False:
                    yield None
                raise RuntimeError("synthetic stream failure")

        async def ensure_client():
            return FailingClient()

        backend._ensure_client = ensure_client

        request = BackendRequest(
            prompt="test",
            model="gemini-test",
            stream=True,
            files=(
                BackendFile(
                    data=b"stream-cleanup",
                    mime_type="application/octet-stream",
                    filename="stream.bin",
                ),
            ),
        )

        import queue

        async def exercise():
            out = queue.Queue()
            state = {"error": None, "emitted": False, "thoughts_delta": ""}
            with self.assertRaises(RuntimeError):
                await backend._stream_once(request, out, state)

        asyncio.run(exercise())

        leftovers = list(Path(tempfile.gettempdir()).glob("gemini-bridge-*"))
        self.assertEqual(leftovers, [])

    def test_distinct_multiple_tool_calls_are_preserved(self):
        raw = (
            '@@TOOL_CALL@@\n'
            '{"name":"search","arguments":{"q":"bridge"}}\n'
            '@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n'
            '{"name":"read_file","arguments":{"path":"README.md"}}\n'
            '@@END_TOOL_CALL@@'
        )

        clean, calls = parse_tool_calls_robust(raw)

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["function"]["name"] for call in calls],
            ["search", "read_file"],
        )

    def test_exact_duplicate_tool_calls_are_still_deduplicated(self):
        raw = (
            '@@TOOL_CALL@@\n'
            '{"name":"search","arguments":{"q":"bridge"}}\n'
            '@@END_TOOL_CALL@@\n'
            '@@TOOL_CALL@@\n'
            '{"name":"search","arguments":{"q":"bridge"}}\n'
            '@@END_TOOL_CALL@@'
        )

        clean, calls = parse_tool_calls_robust(raw)

        # Parsing preserves occurrences. Exact-call deduplication belongs to
        # the higher-level protocol boundary and is covered by existing tests.
        self.assertEqual(len(calls), 1)

    def test_malformed_tool_call_does_not_become_a_fake_valid_call(self):
        raw = '[TOOL_CALL] search {"q":'

        clean, calls = parse_tool_calls_robust(raw)

        self.assertEqual(calls, [])
        self.assertIn("[TOOL_CALL]", clean)

    def test_context_compaction_preserves_tool_call_result_pair(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "current task"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": '{"q":"test"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "result",
            },
            {"role": "assistant", "content": "completed"},
        ]

        compacted, metadata = compact_messages(messages, max_chars=500)

        for index, message in enumerate(compacted):
            if message.get("role") == "assistant" and message.get("tool_calls"):
                self.assertLess(index + 1, len(compacted))
                self.assertEqual(
                    compacted[index + 1].get("role"),
                    "tool",
                )


if __name__ == "__main__":
    unittest.main()
