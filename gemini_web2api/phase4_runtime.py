"""Runtime integration for Phase 4 and Phase 5 reliability features."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from types import ModuleType

from .config import CONFIG
from .grounding import GroundingFacts
from .observability import TRACE_HEADER, elapsed_ms, new_trace_id, request_summary, response_summary
from . import tools as phase4_tools
from .recovery import classify_exception, classify_upstream_text

_state = threading.local()


def _set_request(req: dict | None) -> None:
    _state.grounding = GroundingFacts.from_request(req)


def _clear_request() -> None:
    if hasattr(_state, "grounding"):
        delattr(_state, "grounding")


def _current_grounding() -> GroundingFacts | None:
    return getattr(_state, "grounding", None)


def _safe_path(value: object) -> str:
    return re.sub(r"([?&](?:key|api[_-]?key|token|access_token)=)[^&\s]+", r"\1[REDACTED]", str(value), flags=re.I)


def _module_for(cls) -> ModuleType:
    return sys.modules[cls.__module__]


def install_phase4_runtime(handler_cls) -> None:
    """Install the Phase 4/5 contract on legacy and modular handlers."""
    if getattr(handler_cls, "_phase4_installed", False):
        return

    module = _module_for(handler_cls)
    original_post = handler_cls.do_POST
    original_get = getattr(handler_cls, "do_GET", None)
    original_log_message = getattr(handler_cls, "log_message", None)
    original_chat = getattr(handler_cls, "_handle_chat", None)
    original_responses = getattr(handler_cls, "_handle_responses", None)
    original_generate = getattr(module, "gemini_stream_generate", None)

    def send_json(self, data, status=200):
        trace_id = getattr(self, "_phase4_trace_id", None)
        body = json.dumps(data, ensure_ascii=False).encode()
        self._phase4_status = int(status)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if trace_id:
            self.send_header(TRACE_HEADER, trace_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def start_sse(self):
        self._phase4_status = 200
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        trace_id = getattr(self, "_phase4_trace_id", None)
        if trace_id:
            self.send_header(TRACE_HEADER, trace_id)
        self.end_headers()

    def log_message(self, fmt, *args):
        if original_log_message:
            safe_args = tuple(_safe_path(a) for a in args)
            return original_log_message(self, fmt, *safe_args)

    def do_post(self, *args, **kwargs):
        self._phase4_trace_id = new_trace_id()
        self._phase4_started = time.monotonic()
        self._phase4_status = 500
        self._phase4_tool_names = []
        try:
            result = original_post(self, *args, **kwargs)
            module.log(str(response_summary(self._phase4_trace_id, getattr(self, "_phase4_status", 200), elapsed_ms(self._phase4_started), tool_names=self._phase4_tool_names)))
            return result
        finally:
            _clear_request()

    def do_get(self, *args, **kwargs):
        self._phase4_trace_id = new_trace_id()
        self._phase4_started = time.monotonic()
        self._phase4_status = 500
        try:
            result = original_get(self, *args, **kwargs) if original_get else None
            module.log(str(response_summary(self._phase4_trace_id, getattr(self, "_phase4_status", 200), elapsed_ms(self._phase4_started))))
            return result
        finally:
            _clear_request()

    def handle_chat(self, body):
        try:
            req = json.loads(body) if isinstance(body, (bytes, bytearray)) else body
        except (TypeError, json.JSONDecodeError):
            req = None
        _set_request(req)
        return original_chat(self, body) if original_chat else None

    def handle_responses(self, body):
        try:
            req = json.loads(body) if isinstance(body, (bytes, bytearray)) else body
        except (TypeError, json.JSONDecodeError):
            req = None
        _set_request(req)
        return original_responses(self, body) if original_responses else None

    def phase4_messages(messages, tools=None, tool_choice=None, *args, **kwargs):
        return phase4_tools.messages_to_prompt(
            messages,
            tools,
            tool_choice,
            grounding=_current_grounding(),
            max_chars=int(CONFIG.get("prompt_soft_budget_chars", 0) or 0),
        )

    handler_cls.send_json = send_json
    if hasattr(handler_cls, "_start_sse"):
        handler_cls._start_sse = start_sse
    handler_cls.log_message = log_message
    handler_cls.do_POST = do_post
    if original_get:
        handler_cls.do_GET = do_get
    if original_chat:
        handler_cls._handle_chat = handle_chat
    if original_responses:
        handler_cls._handle_responses = handle_responses

    module.messages_to_prompt = phase4_messages
    module.parse_tool_calls = phase4_tools.parse_tool_calls

    if original_generate and not getattr(module, "_phase5_generate_wrapped", False):
        def generate_with_recovery(*args, **kwargs):
            try:
                raw = original_generate(*args, **kwargs)
            except Exception as exc:
                failure = classify_exception(exc)
                module.log(f"Phase5 upstream failure type={failure.error_type.value} retryable={failure.retryable}")
                raise RuntimeError(f"upstream {failure.error_type.value}: {failure.message}") from None

            failure = classify_upstream_text(raw)
            if failure is not None:
                if failure.error_type.value == "empty_response":
                    module.log("Phase5 upstream failure type=empty_response after bounded upstream retries")
                    raise RuntimeError("upstream empty_response: Gemini returned no usable response")
                module.log(f"Phase5 upstream failure type={failure.error_type.value} retryable={failure.retryable}")
                raise RuntimeError(f"upstream {failure.error_type.value}: {failure.message}")
            return raw

        module.gemini_stream_generate = generate_with_recovery
        module._phase5_generate_wrapped = True

    handler_cls._phase4_installed = True
    module.log(str(request_summary("RUNTIME", "phase4", "phase4+phase5 installed", 0)))
