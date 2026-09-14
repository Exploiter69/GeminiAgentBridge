"""Production installation for safe observability and response semantics."""
from __future__ import annotations

import contextvars
import functools
import json
import sys
import time

from .observability import TRACE_HEADER, emit_event, new_trace_id
from .response_semantics import remove_fabricated_usage, sanitize_sse_event

_CURRENT_HANDLER = contextvars.ContextVar("gemini_bridge_current_handler", default=None)


class _SSEWriteProxy:
    """Proxy handler output so post-header SSE events remain semantically valid."""

    def __init__(self, wrapped, handler):
        self._wrapped = wrapped
        self._handler = handler
        self._buffer = b""

    def write(self, data):
        self._buffer += bytes(data)
        while b"\n\n" in self._buffer:
            event, self._buffer = self._buffer.split(b"\n\n", 1)
            if self._handler._bridge_stream_failed and b"data: [DONE]" in event:
                continue
            self._wrapped.write(sanitize_sse_event(event + b"\n\n"))
        return len(data)

    def flush(self):
        if self._buffer:
            if not (self._handler._bridge_stream_failed and b"data: [DONE]" in self._buffer):
                self._wrapped.write(sanitize_sse_event(self._buffer))
            self._buffer = b""
        return self._wrapped.flush()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _install_stream_failure_marker(handler_cls) -> None:
    """Mark the current request when an upstream stream fails after headers commit."""
    module = sys.modules.get(handler_cls.__module__)
    if module is None or getattr(module, "_bridge_stream_failure_installed", False):
        return
    original_stream = getattr(module, "generate_stream", None)
    if not callable(original_stream):
        return

    @functools.wraps(original_stream)
    def guarded_stream(*args, **kwargs):
        handler = _CURRENT_HANDLER.get()
        try:
            yield from original_stream(*args, **kwargs)
        except Exception:
            if handler is not None:
                handler._bridge_stream_failed = True
            raise

    module.generate_stream = guarded_stream
    module._bridge_stream_failure_installed = True


def install_observability(handler_cls) -> None:
    """Install bounded trace lifecycle and response semantic guards."""
    if getattr(handler_cls, "_bridge_observability_installed", False):
        return

    original_end_headers = handler_cls.end_headers
    original_do_get = handler_cls.do_GET
    original_do_post = handler_cls.do_POST
    original_send_json = handler_cls.send_json
    _install_stream_failure_marker(handler_cls)

    def end_headers(self):
        trace_id = getattr(self, "_bridge_trace_id", None)
        if trace_id:
            self.send_header(TRACE_HEADER, trace_id)
        return original_end_headers(self)

    def send_json(self, data, status=200):
        # Gemini Web does not expose authoritative OpenAI token accounting.
        return original_send_json(self, remove_fabricated_usage(data), status)

    @functools.wraps(original_do_get)
    def do_get(self):
        trace_id = new_trace_id()
        self._bridge_trace_id = trace_id
        started = time.monotonic()
        emit_event(trace_id, "request_received", method="GET", path=self.path)
        try:
            result = original_do_get(self)
            emit_event(trace_id, "request_completed", method="GET", path=self.path, duration_ms=int((time.monotonic() - started) * 1000))
            return result
        except Exception as exc:
            emit_event(trace_id, "request_failed", method="GET", path=self.path, error=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
            raise

    @functools.wraps(original_do_post)
    def do_post(self):
        trace_id = new_trace_id()
        self._bridge_trace_id = trace_id
        self._bridge_stream_failed = False
        started = time.monotonic()
        emit_event(trace_id, "request_received", method="POST", path=self.path)
        original_wfile = self.wfile
        self.wfile = _SSEWriteProxy(original_wfile, self)
        token = _CURRENT_HANDLER.set(self)
        try:
            result = original_do_post(self)
            if self._bridge_stream_failed:
                error_event = {
                    "type": "error",
                    "error": {
                        "message": "upstream stream failed after response commitment",
                        "code": "upstream_stream_error",
                        "trace_id": trace_id,
                    },
                }
                self.wfile.write(("event: error\ndata: " + json.dumps(error_event, separators=(",", ":")) + "\n\n").encode())
                self.wfile.flush()
            emit_event(trace_id, "request_completed", method="POST", path=self.path, duration_ms=int((time.monotonic() - started) * 1000), stream_failed=bool(self._bridge_stream_failed))
            return result
        except Exception as exc:
            emit_event(trace_id, "request_failed", method="POST", path=self.path, error=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
            raise
        finally:
            _CURRENT_HANDLER.reset(token)
            try:
                self.wfile.flush()
            except Exception:
                pass
            self.wfile = original_wfile

    handler_cls.end_headers = end_headers
    handler_cls.send_json = send_json
    handler_cls.do_GET = do_get
    handler_cls.do_POST = do_post
    handler_cls._bridge_observability_installed = True
