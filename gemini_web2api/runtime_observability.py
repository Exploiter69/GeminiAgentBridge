"""Production installation for the safe Phase 10 observability layer."""
from __future__ import annotations

import functools
import time

from .observability import TRACE_HEADER, emit_event, new_trace_id


def install_observability(handler_cls) -> None:
    """Install bounded trace lifecycle events without logging request content."""
    if getattr(handler_cls, "_bridge_observability_installed", False):
        return

    original_end_headers = handler_cls.end_headers
    original_do_get = handler_cls.do_GET
    original_do_post = handler_cls.do_POST

    def end_headers(self):
        trace_id = getattr(self, "_bridge_trace_id", None)
        if trace_id:
            self.send_header(TRACE_HEADER, trace_id)
        return original_end_headers(self)

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
        started = time.monotonic()
        emit_event(trace_id, "request_received", method="POST", path=self.path)
        try:
            result = original_do_post(self)
            emit_event(trace_id, "request_completed", method="POST", path=self.path, duration_ms=int((time.monotonic() - started) * 1000))
            return result
        except Exception as exc:
            emit_event(trace_id, "request_failed", method="POST", path=self.path, error=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
            raise

    handler_cls.end_headers = end_headers
    handler_cls.do_GET = do_get
    handler_cls.do_POST = do_post
    handler_cls._bridge_observability_installed = True
