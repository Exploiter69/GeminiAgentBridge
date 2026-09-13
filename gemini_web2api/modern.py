"""Modern Gemini Web transport backed by the maintained gemini-webapi client.

The original bridge used the legacy StreamGenerate HTTP endpoint directly. Google
has changed the Gemini Web transport repeatedly, so the bridge keeps the legacy
protocol implementation for explicit compatibility but uses gemini-webapi as the
live transport by default. This module contains no downstream tool execution.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import queue
import threading

from .config import CONFIG

try:
    from gemini_webapi import GeminiClient
except ImportError:  # pragma: no cover - exercised only in minimal installs
    GeminiClient = None


class ModernBackendUnavailable(RuntimeError):
    """Raised when the maintained Gemini Web transport is not installed."""


class _ModernBackend:
    def __init__(self) -> None:
        self._loop = None
        self._thread = None
        self._client = None
        self._lock = threading.Lock()
        self._started = threading.Event()

    def _ensure_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            def runner() -> None:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._started.set()
                self._loop.run_forever()
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()

            self._started.clear()
            self._thread = threading.Thread(target=runner, name="gemini-webapi-loop", daemon=True)
            self._thread.start()
            if not self._started.wait(5):
                raise RuntimeError("modern Gemini transport event loop failed to start")

    def _run(self, coro, timeout=None):
        self._ensure_loop()
        timeout = timeout or max(30, int(CONFIG.get("request_timeout_sec", 180)) + 15)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    @staticmethod
    def _cookie_values() -> tuple[str, str]:
        cookie_file = CONFIG.get("cookie_file")
        if not cookie_file or not os.path.exists(cookie_file):
            return "", ""
        try:
            with open(cookie_file, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
            direct_psid = direct_psidts = ""
            if raw.startswith("{"):
                data = json.loads(raw)
                direct_psid = str(data.get("__Secure-1PSID", ""))
                direct_psidts = str(data.get("__Secure-1PSIDTS", ""))
                cookie_str = str(data.get("cookie", ""))
            else:
                cookie_str = raw
            pairs = {}
            for item in cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    pairs[key.strip()] = value.strip()
            return (
                direct_psid or pairs.get("__Secure-1PSID", ""),
                direct_psidts or pairs.get("__Secure-1PSIDTS", ""),
            )
        except Exception as exc:
            raise RuntimeError("unable to read Gemini cookie file") from exc

    async def _close_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass

    async def _ensure_client(self):
        if GeminiClient is None:
            raise ModernBackendUnavailable(
                "gemini-webapi is not installed; run: pip install -r requirements.txt"
            )
        if self._client is not None:
            return self._client

        psid, psidts = self._cookie_values()
        if not psid:
            raise RuntimeError("Gemini Web authentication cookie is not configured")

        client = GeminiClient(psid, psidts, proxy=CONFIG.get("proxy") or None)
        await client.init(
            timeout=max(30, int(CONFIG.get("request_timeout_sec", 180))),
            auto_close=False,
            auto_refresh=True,
        )
        self._client = client
        return client

    @staticmethod
    def _model_for_mode(model_id: int) -> str:
        return {
            1: "gemini-flash",
            2: "gemini-flash",
            3: "gemini-pro",
            4: "gemini-flash",
            5: "gemini-flash",
            6: "gemini-flash-lite",
        }.get(model_id, "gemini-flash")

    async def _generate_once(self, prompt: str, model_id: int) -> str:
        client = await self._ensure_client()
        response = await client.generate_content(
            prompt,
            model=self._model_for_mode(model_id),
            temporary=bool(CONFIG.get("temporary_chats", False)),
        )
        text = getattr(response, "text", None) or str(response or "")
        if not text.strip():
            raise RuntimeError("Gemini Web returned an empty response")
        return text

    async def _generate(self, prompt: str, model_id: int) -> str:
        attempts = max(1, int(CONFIG.get("retry_attempts", 3)))
        last_error = None
        for attempt in range(attempts):
            try:
                return await self._generate_once(prompt, model_id)
            except Exception as exc:
                last_error = exc
                name = type(exc).__name__.lower()
                if "auth" in name or "session" in name or "model" in name:
                    await self._close_client()
                if attempt + 1 >= attempts:
                    break
                delay = min(
                    float(CONFIG.get("retry_delay_sec", 2)) * (2 ** attempt),
                    float(CONFIG.get("retry_max_delay_sec", 8)),
                )
                await asyncio.sleep(delay)
        raise last_error

    async def _stream_once(self, prompt: str, model_id: int, out: queue.Queue) -> None:
        client = await self._ensure_client()
        async for chunk in client.generate_content_stream(
            prompt,
            model=self._model_for_mode(model_id),
            temporary=bool(CONFIG.get("temporary_chats", False)),
        ):
            delta = getattr(chunk, "text_delta", None)
            if delta:
                out.put(delta)

    def generate(self, prompt: str, model_id: int) -> str:
        return self._run(self._generate(prompt, model_id))

    def generate_stream(self, prompt: str, model_id: int):
        out: queue.Queue = queue.Queue()
        sentinel = object()
        state = {"error": None}

        async def producer():
            attempts = max(1, int(CONFIG.get("retry_attempts", 3)))
            for attempt in range(attempts):
                try:
                    await self._stream_once(prompt, model_id, out)
                    out.put(sentinel)
                    return
                except Exception as exc:
                    state["error"] = exc
                    name = type(exc).__name__.lower()
                    if "auth" in name or "session" in name or "model" in name:
                        await self._close_client()
                    if attempt + 1 >= attempts:
                        break
                    await asyncio.sleep(min(
                        float(CONFIG.get("retry_delay_sec", 2)) * (2 ** attempt),
                        float(CONFIG.get("retry_max_delay_sec", 8)),
                    ))
            out.put(sentinel)

        self._ensure_loop()
        asyncio.run_coroutine_threadsafe(producer(), self._loop)
        while True:
            item = out.get()
            if item is sentinel:
                if state["error"] is not None:
                    raise state["error"]
                return
            yield item

    def shutdown(self) -> None:
        if not self._loop or not self._thread:
            return
        try:
            self._run(self._close_client(), timeout=10)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


_BACKEND = _ModernBackend()
atexit.register(_BACKEND.shutdown)


def generate(prompt: str, model_id: int) -> str:
    """Generate through the maintained Gemini Web client."""
    return _BACKEND.generate(prompt, model_id)


def generate_stream(prompt: str, model_id: int):
    """Stream through the maintained Gemini Web client."""
    yield from _BACKEND.generate_stream(prompt, model_id)
