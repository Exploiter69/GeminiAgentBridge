"""Modern Gemini Web transport backed by gemini-webapi 2.1.1."""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import queue
import tempfile
import threading
from pathlib import Path

from .backend import (
    BackendCapabilities,
    BackendCapabilityError,
    BackendFile,
    BackendHealth,
    BackendHealthState,
    BackendRequest,
    BackendResponse,
)
from .config import CONFIG

try:
    from gemini_webapi import GeminiClient
except ImportError:  # pragma: no cover
    GeminiClient = None


class ModernBackendUnavailable(RuntimeError):
    """Raised when the maintained Gemini Web transport is not installed."""


class _ModernBackend:
    capabilities = BackendCapabilities(
        files=True,
        streaming=True,
        dynamic_models=True,
        thoughts=True,
        temporary=True,
        provider_options=False,
    )

    def __init__(self) -> None:
        self._loop = None
        self._thread = None
        self._client = None
        self._lock = threading.Lock()
        self._async_lock = None
        self._started = threading.Event()
        self._health_lock = threading.Lock()
        self._health = BackendHealth(BackendHealthState.STOPPED)

    def _set_health(self, state: BackendHealthState, *, initialized=None, authenticated=None,
                    model_catalog=None, error=None) -> None:
        with self._health_lock:
            current = self._health
            self._health = BackendHealth(
                state=state,
                initialized=current.initialized if initialized is None else initialized,
                authenticated=current.authenticated if authenticated is None else authenticated,
                model_catalog=current.model_catalog if model_catalog is None else model_catalog,
                last_error=None if error is None and state == BackendHealthState.READY else (
                    current.last_error if error is None else str(error)
                ),
            )

    def health(self) -> BackendHealth:
        with self._health_lock:
            return self._health

    def _ensure_loop(self) -> None:
        if self._thread and self._thread.is_alive() and self._loop and not self._loop.is_closed():
            return
        with self._lock:
            if self._thread and self._thread.is_alive() and self._loop and not self._loop.is_closed():
                return
            self._set_health(BackendHealthState.STARTING)
            def runner() -> None:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._async_lock = asyncio.Lock()
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
                self._set_health(BackendHealthState.FAILED, initialized=False, authenticated=False,
                                 error="modern Gemini transport event loop failed to start")
                raise RuntimeError("modern Gemini transport event loop failed to start")

    def _run(self, coro, timeout=None):
        self._ensure_loop()
        loop = self._loop
        if loop is None or loop.is_closed() or not self._thread or not self._thread.is_alive():
            coro.close()
            self._set_health(BackendHealthState.FAILED, initialized=False, error="modern Gemini transport event loop is unavailable")
            raise RuntimeError("modern Gemini transport event loop is unavailable")
        timeout = timeout or max(30, int(CONFIG.get("request_timeout_sec", 180)) + 15)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            raise
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            self._set_health(BackendHealthState.DEGRADED, error="modern Gemini transport request timed out")
            raise
        except BaseException:
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
            return direct_psid or pairs.get("__Secure-1PSID", ""), direct_psidts or pairs.get("__Secure-1PSIDTS", "")
        except Exception as exc:
            raise RuntimeError("unable to read Gemini authentication cookie") from exc

    async def _close_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        self._set_health(BackendHealthState.STARTING, initialized=False, authenticated=False, model_catalog=False)

    async def _ensure_client(self):
        if GeminiClient is None:
            self._set_health(BackendHealthState.FAILED, initialized=False, authenticated=False,
                             error="gemini-webapi is not installed")
            raise ModernBackendUnavailable("gemini-webapi is not installed; run: pip install -r requirements.txt")
        if self._client is not None:
            return self._client
        self._set_health(BackendHealthState.STARTING, initialized=False, authenticated=False)
        psid, psidts = self._cookie_values()
        if not psid:
            self._set_health(BackendHealthState.FAILED, initialized=False, authenticated=False,
                             error="Gemini Web authentication is not configured")
            raise RuntimeError("Gemini Web authentication cookie is not configured")
        client = GeminiClient(psid, psidts, proxy=CONFIG.get("proxy") or None)
        try:
            await client.init(timeout=max(30, int(CONFIG.get("request_timeout_sec", 180))), auto_close=False, auto_refresh=True)
        except Exception as exc:
            try:
                await client.close()
            except Exception:
                pass
            self._set_health(BackendHealthState.FAILED, initialized=False, authenticated=False, error=type(exc).__name__)
            raise
        self._client = client
        self._set_health(BackendHealthState.READY, initialized=True, authenticated=True)
        return client

    @staticmethod
    def _resolve_model(client, requested: str):
        resolver = getattr(client, "resolve_model", None)
        if callable(resolver):
            try:
                return resolver(requested)
            except Exception as exc:
                raise BackendCapabilityError(f"requested model is unavailable: {requested}") from exc
        return requested

    def resolve_model(self, requested: str):
        self._ensure_loop()
        async def resolve():
            client = await self._ensure_client()
            return self._resolve_model(client, requested)
        return self._run(resolve())

    @staticmethod
    def _materialize_files(files: tuple) -> list[str]:
        temp_paths: list[str] = []
        for item in files:
            data = getattr(item, "data", None)
            filename = getattr(item, "filename", None)
            if data is None:
                if isinstance(item, (str, os.PathLike)) and os.path.exists(item):
                    temp_paths.append(os.fspath(item))
                    continue
                raise BackendCapabilityError("modern backend received a file without local bytes or a local path")
            suffix = Path(filename or "attachment.bin").suffix or ".bin"
            handle = tempfile.NamedTemporaryFile(prefix="gemini-bridge-", suffix=suffix, delete=False)
            try:
                handle.write(data)
                handle.flush()
            finally:
                handle.close()
            temp_paths.append(handle.name)
        return temp_paths

    @staticmethod
    def _cleanup_files(paths: list[str], original: tuple) -> None:
        original_paths = {os.fspath(item) for item in original if isinstance(item, (str, os.PathLike)) and os.path.exists(item)}
        for path in paths:
            if path in original_paths:
                continue
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _kwargs(client, request: BackendRequest, files: list[str]) -> dict:
        kwargs = {"model": _ModernBackend._resolve_model(client, request.model), "temporary": request.temporary}
        if files:
            kwargs["files"] = files
        if request.think_mode not in (None, 0):
            raise BackendCapabilityError(
                "modern Gemini Web transport does not expose a numeric think level; select a thinking-capable model instead"
            )
        if request.provider_options:
            raise BackendCapabilityError("provider-specific options are not supported by the modern Gemini Web client")
        return kwargs

    async def _generate_once(self, request: BackendRequest) -> BackendResponse:
        if self._async_lock is None:
            raise RuntimeError("modern Gemini transport lock is unavailable")
        async with self._async_lock:
            client = await self._ensure_client()
            paths = self._materialize_files(request.files)
            try:
                response = await client.generate_content(request.prompt, **self._kwargs(client, request, paths))
                text = getattr(response, "text", None) or str(response or "")
                if not text.strip():
                    raise RuntimeError("Gemini Web returned an empty response")
                thoughts = getattr(response, "thoughts", None) or ""
                return BackendResponse(text=text, thoughts=str(thoughts), raw=response)
            finally:
                self._cleanup_files(paths, request.files)

    @classmethod
    def _is_retryable_error(cls, exc: Exception) -> bool:
        """Retry only failures that are plausibly transient.

        Never retry rate limits, authentication/authorization failures,
        model/request errors, or other deterministic upstream failures.
        """
        if isinstance(exc, (asyncio.CancelledError, BackendCapabilityError)):
            return False

        if cls._is_session_error(exc):
            return False

        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)

        if status is not None:
            try:
                status = int(status)
            except (TypeError, ValueError):
                status = None

        if status is not None:
            if status == 429:
                return False
            if status in {401, 403, 400, 404, 409, 422}:
                return False
            if status in {408, 425} or 500 <= status <= 599:
                return True
            return False

        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True

        name = type(exc).__name__.lower()
        text = str(exc).lower()

        transient_tokens = (
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "connection refused",
            "temporarily unavailable",
            "temporary failure",
            "transport error",
            "remote protocol",
            "server disconnected",
        )

        if any(token in name or token in text for token in transient_tokens):
            return True

        # Empty responses are deterministic and retrying them can duplicate
        # an otherwise successful upstream request.
        return False

    async def _generate(self, request: BackendRequest) -> BackendResponse:
        attempts = max(1, int(CONFIG.get("retry_attempts", 3)))
        last_error = None
        for attempt in range(attempts):
            try:
                return await self._generate_once(request)
            except asyncio.CancelledError:
                raise
            except BackendCapabilityError:
                raise
            except Exception as exc:
                last_error = exc
                if self._is_session_error(exc):
                    await self._close_client()
                if (
                    attempt + 1 >= attempts
                    or not self._is_retryable_error(exc)
                ):
                    break
                delay = min(
                    float(CONFIG.get("retry_delay_sec", 2)) * (2 ** attempt),
                    float(CONFIG.get("retry_max_delay_sec", 8)),
                )
                await asyncio.sleep(delay)
        self._set_health(
            BackendHealthState.DEGRADED,
            error=type(last_error).__name__ if last_error else "unknown error",
        )
        raise last_error

    async def _stream_once(self, request: BackendRequest, out: queue.Queue, state: dict) -> None:
        if self._async_lock is None:
            raise RuntimeError("modern Gemini transport lock is unavailable")
        async with self._async_lock:
            client = await self._ensure_client()
            paths = self._materialize_files(request.files)
            try:
                async for chunk in client.generate_content_stream(request.prompt, **self._kwargs(client, request, paths)):
                    thoughts = getattr(chunk, "thoughts_delta", None)
                    if thoughts:
                        state["thoughts_delta"] = str(thoughts)
                    delta = getattr(chunk, "text_delta", None)
                    if delta:
                        state["emitted"] = True
                        out.put(delta)
                if not state["emitted"]:
                    raise RuntimeError("Gemini Web returned an empty stream")
            finally:
                self._cleanup_files(paths, request.files)

    @staticmethod
    def _is_session_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return any(token in text for token in ("unauthenticated", "permission denied", "forbidden", "unauthorized", "auth", "session expired", "invalid session", "model not found"))

    def generate_response(self, request: BackendRequest) -> BackendResponse:
        return self._run(self._generate(request))

    def generate(self, prompt: str, model_id, **kwargs) -> str:
        model = kwargs.pop("model", None)
        if model is None:
            model = {1: "gemini-flash", 2: "gemini-flash", 3: "gemini-pro", 4: "gemini-flash", 5: "gemini-flash", 6: "gemini-flash-lite"}.get(model_id, str(model_id))
        request = BackendRequest.from_legacy_args(prompt, str(model), **kwargs)
        return self.generate_response(request).text

    def list_models(self):
        return self._run(self._list_models())

    async def _list_models(self):
        client = await self._ensure_client()
        models = getattr(client, "list_models", None)
        if not callable(models):
            raise ModernBackendUnavailable("installed gemini-webapi client cannot enumerate models")
        result = list(models() or [])
        self._set_health(BackendHealthState.READY, model_catalog=True)
        return result

    def generate_stream_response(self, request: BackendRequest):
        out: queue.Queue = queue.Queue()
        sentinel = object()
        state = {"error": None, "emitted": False, "thoughts_delta": ""}
        self._ensure_loop()
        loop = self._loop
        async def producer():
            attempts = max(1, int(CONFIG.get("retry_attempts", 3)))
            for attempt in range(attempts):
                try:
                    await self._stream_once(request, out, state)
                    out.put(sentinel)
                    return
                except asyncio.CancelledError:
                    raise
                except BackendCapabilityError as exc:
                    state["error"] = exc
                    break
                except Exception as exc:
                    state["error"] = exc
                    if self._is_session_error(exc):
                        await self._close_client()

                    # Once bytes have been emitted, retrying would duplicate
                    # downstream-visible output and potentially side effects.
                    if (
                        state["emitted"]
                        or attempt + 1 >= attempts
                        or not self._is_retryable_error(exc)
                    ):
                        break

                    await asyncio.sleep(
                        min(
                            float(CONFIG.get("retry_delay_sec", 2)) * (2 ** attempt),
                            float(CONFIG.get("retry_max_delay_sec", 8)),
                        )
                    )
            self._set_health(BackendHealthState.DEGRADED, error=type(state["error"]).__name__ if state["error"] else "stream failed")
            out.put(sentinel)
        future = asyncio.run_coroutine_threadsafe(producer(), loop)
        try:
            while True:
                item = out.get()
                if item is sentinel:
                    if state["error"] is not None:
                        raise state["error"]
                    return
                yield item
        except (GeneratorExit, KeyboardInterrupt):
            future.cancel()
            raise
        finally:
            if not future.done():
                future.cancel()

    def generate_stream(self, prompt: str, model_id, **kwargs):
        model = kwargs.pop("model", None)
        if model is None:
            model = {1: "gemini-flash", 2: "gemini-flash", 3: "gemini-pro", 4: "gemini-flash", 5: "gemini-flash", 6: "gemini-flash-lite"}.get(model_id, str(model_id))
        request = BackendRequest.from_legacy_args(prompt, str(model), stream=True, **kwargs)
        yield from self.generate_stream_response(request)

    def shutdown(self) -> None:
        with self._lock:
            loop, thread = self._loop, self._thread
            if not loop or not thread:
                self._set_health(BackendHealthState.STOPPED, initialized=False, authenticated=False, model_catalog=False)
                return
            if loop.is_closed() or not thread.is_alive():
                self._loop = None; self._thread = None; self._client = None
                self._set_health(BackendHealthState.STOPPED, initialized=False, authenticated=False, model_catalog=False)
                return
            try:
                close_future = asyncio.run_coroutine_threadsafe(self._close_client(), loop)
                close_future.result(timeout=5)
            except Exception:
                pass
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)
            self._loop = None; self._thread = None; self._client = None; self._async_lock = None
            self._set_health(BackendHealthState.STOPPED, initialized=False, authenticated=False, model_catalog=False)


_BACKEND = _ModernBackend()
atexit.register(_BACKEND.shutdown)


def generate(request_or_prompt, model_id=None, **kwargs) -> str:
    if isinstance(request_or_prompt, BackendRequest):
        return _BACKEND.generate_response(request_or_prompt).text
    return _BACKEND.generate(request_or_prompt, model_id, **kwargs)


def generate_response(request: BackendRequest) -> BackendResponse:
    return _BACKEND.generate_response(request)


def generate_stream(request_or_prompt, model_id=None, **kwargs):
    if isinstance(request_or_prompt, BackendRequest):
        yield from _BACKEND.generate_stream_response(request_or_prompt)
    else:
        yield from _BACKEND.generate_stream(request_or_prompt, model_id, **kwargs)


def health() -> BackendHealth:
    return _BACKEND.health()


def shutdown() -> None:
    _BACKEND.shutdown()
