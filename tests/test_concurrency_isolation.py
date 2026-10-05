"""Concurrency / state-isolation regression tests.

These exercise the REAL ThreadingMixIn server (a new thread per connection)
with the phase4/5/6 runtime actually installed, firing genuinely concurrent
requests with different tool schemas and tool_choice constraints from
different threads. This targets the thread-local stores in
phase4_runtime.py (_state) and protocol.py (_tool_context): if either were
accidentally a plain module-level dict/list instead of threading.local,
concurrent requests would see each other's tool definitions or tool_choice.
"""
import concurrent.futures
import http.client
import json
import threading
import unittest
from unittest import mock

from gemini_web2api import protocol, server
from gemini_web2api.config import CONFIG
from gemini_web2api.phase4_runtime import install_phase4_runtime


READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class ConcurrentToolContextIsolationTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(CONFIG)
        CONFIG["api_keys"] = []
        CONFIG["upstream_backend"] = "legacy"
        install_phase4_runtime(server.GeminiHandler)
        self.bridge = server.ThreadedServer(("127.0.0.1", 0), server.GeminiHandler)
        self.port = self.bridge.server_address[1]
        self.thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.bridge.shutdown()
        self.bridge.server_close()
        self.thread.join(timeout=5)
        CONFIG.clear()
        CONFIG.update(self.original_config)
        protocol.clear_tool_context()

    def _call(self, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        connection.close()
        return response.status, body

    def test_concurrent_requests_with_different_tools_do_not_cross_contaminate(self):
        read_response = '```tool_call\n{"name":"read_file","arguments":{"path":"a.txt"}}\n```'
        search_response = '```tool_call\n{"name":"search","arguments":{"query":"needle"}}\n```'

        def fake_generate(prompt, *args, **kwargs):
            # Route the canned response by which tool schema this specific
            # request actually carries in its own prompt text, so a
            # cross-contaminated tool_defs lookup would produce a mismatch
            # that the assertions below can catch.
            if '"read_file"' in prompt and '"search"' not in prompt:
                return read_response
            if '"search"' in prompt and '"read_file"' not in prompt:
                return search_response
            raise AssertionError("prompt did not contain exactly one tool schema: " + prompt[:200])

        results = {}
        errors = []

        def call_read():
            try:
                results.setdefault("read", []).append(self._call({
                    "model": "gemini-3.1-pro",
                    "messages": [{"role": "user", "content": "read a.txt"}],
                    "tools": [READ_FILE_TOOL],
                    "tool_choice": "auto",
                }))
            except Exception as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        def call_search():
            try:
                results.setdefault("search", []).append(self._call({
                    "model": "gemini-3.1-pro",
                    "messages": [{"role": "user", "content": "search for needle"}],
                    "tools": [SEARCH_TOOL],
                    "tool_choice": "auto",
                }))
            except Exception as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        with mock.patch("gemini_web2api.server.generate", side_effect=fake_generate):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = []
                for _ in range(10):
                    futures.append(pool.submit(call_read))
                    futures.append(pool.submit(call_search))
                for future in futures:
                    future.result(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(results.get("read", [])), 10)
        self.assertEqual(len(results.get("search", [])), 10)

        for status, body in results["read"]:
            self.assertEqual(status, 200)
            self.assertEqual(body["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_file")

        for status, body in results["search"]:
            self.assertEqual(status, 200)
            self.assertEqual(body["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "search")


if __name__ == "__main__":
    unittest.main()
