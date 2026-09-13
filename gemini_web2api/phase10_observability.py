"""Phase 10 observability integration.

This layer instruments the existing Phase 4/5/6 runtime without changing tool
execution ownership. It emits safe lifecycle events and exposes the current
trace through the existing ``X-Bridge-Trace-Id`` response header.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from types import ModuleType

from .observability import elapsed_ms, emit_event, event_json, new_trace_id, safe_tool_names
from .protocol import validate_tool_calls
from . import phase4_runtime

_state = threading.local()


def _module_for(cls) -> ModuleType:
    return sys.modules[cls.__module__]


def _trace_id() -> str | None:
    return getattr(_state, "trace_id", None)


def _log(module: ModuleType, trace_id: str, event: str, **fields) -> None:
    event_obj = emit_event(trace_id, event, **fields)
    module.log(event_json(event_obj))


def install_phase10_observability(handler_cls) -> None:
    """Install the Phase 10 trace/audit layer exactly once."""
    if getattr(handler_cls, "_phase10_observability_installed", False):
        return

    module = _module_for(handler_cls)
    original_post = handler_cls.do_POST
    original_get = getattr(handler_cls, "do_GET", None)
    original_read = getattr(handler_cls, "_read_request_body", None)
    original_chat = getattr(handler_cls, "_handle_chat", None)
    original_responses = getattr(handler_cls, "_handle_responses", None)
    original_google = getattr(handler_cls, "_handle_google_generate", None)
    original_prompt = getattr(module, "messages_to_prompt", None)
    original_parse = getattr(module, "parse_tool_calls", None)
    original_generate = getattr(module, "generate", None)
    original_stream = getattr(module, "generate_stream", None)

    def read_request_body(self, *args, **kwargs):
        body = original_read(self, *args, **kwargs) if original_read else b""
        self._phase10_body_bytes = len(body or b"")
        return body

    def do_post(self, *args, **kwargs):
        result = original_post(self, *args, **kwargs)
        trace_id = getattr(self, "_phase4_trace_id", None) or new_trace_id()
        self._phase10_trace_id = trace_id
        _state.trace_id = trace_id
        try:
            status = int(getattr(self, "_phase4_status", 200))
            _log(
                module,
                trace_id,
                "request_completed" if status < 500 else "request_failed",
                method="POST",
                path=getattr(self, "path", "").split("?", 1)[0],
                status=status,
                duration_ms=elapsed_ms(getattr(self, "_phase4_started", time.monotonic())),
                body_bytes=getattr(self, "_phase10_body_bytes", 0),
                tool_names=getattr(self, "_phase4_tool_names", []),
            )
        finally:
            if hasattr(_state, "trace_id"):
                del _state.trace_id
        return result

    def do_get(self, *args, **kwargs):
        result = original_get(self, *args, **kwargs) if original_get else None
        trace_id = getattr(self, "_phase4_trace_id", None) or new_trace_id()
        _state.trace_id = trace_id
        try:
            status = int(getattr(self, "_phase4_status", 200))
            _log(
                module,
                trace_id,
                "request_completed" if status < 500 else "request_failed",
                method="GET",
                path=getattr(self, "path", "").split("?", 1)[0],
                status=status,
                duration_ms=elapsed_ms(getattr(self, "_phase4_started", time.monotonic())),
            )
        finally:
            if hasattr(_state, "trace_id"):
                del _state.trace_id
        return result

    def handle_chat(self, body, *args, **kwargs):
        try:
            req = json.loads(body) if isinstance(body, (bytes, bytearray)) else body
        except (TypeError, json.JSONDecodeError):
            req = {}
        trace_id = getattr(self, "_phase4_trace_id", None) or new_trace_id()
        _state.trace_id = trace_id
        _log(module, trace_id, "request_received", method="POST", path="/v1/chat/completions", body_bytes=len(body or b"") if isinstance(body, (bytes, bytearray)) else 0)
        _log(
            module,
            trace_id,
            "context_built",
            message_count=len(req.get("messages", [])) if isinstance(req, dict) else 0,
            tool_count=len(req.get("tools") or []) if isinstance(req, dict) else 0,
            tool_choice=str(req.get("tool_choice", "auto")) if isinstance(req, dict) else "auto",
            grounding_explicit=bool((req.get("metadata") or {}).get("grounding")) if isinstance(req, dict) else False,
        )
        return original_chat(self, body, *args, **kwargs) if original_chat else None

    def handle_responses(self, body, *args, **kwargs):
        try:
            req = json.loads(body) if isinstance(body, (bytes, bytearray)) else body
        except (TypeError, json.JSONDecodeError):
            req = {}
        trace_id = getattr(self, "_phase4_trace_id", None) or new_trace_id()
        _state.trace_id = trace_id
        _log(module, trace_id, "request_received", method="POST", path="/v1/responses", body_bytes=len(body or b"") if isinstance(body, (bytes, bytearray)) else 0)
        input_items = req.get("input", []) if isinstance(req, dict) else []
        observation_count = 0
        if isinstance(input_items, list):
            observation_count = sum(1 for item in input_items if isinstance(item, dict) and item.get("type") == "function_call_output")
        if observation_count:
            _log(module, trace_id, "observation_received", count=observation_count)
            _log(module, trace_id, "observation_validated", count=observation_count, status="preserved")
            _log(module, trace_id, "next_turn", reason="tool_result_continuity")
        _log(
            module,
            trace_id,
            "context_built",
            input_items=len(input_items) if isinstance(input_items, list) else 1,
            tool_count=len(req.get("tools") or []) if isinstance(req, dict) else 0,
            tool_choice=str(req.get("tool_choice", "auto")) if isinstance(req, dict) else "auto",
        )
        return original_responses(self, body, *args, **kwargs) if original_responses else None

    def handle_google(body, stream, *args, **kwargs):
        trace_id = getattr(self, "_phase4_trace_id", None) or new_trace_id()
        _state.trace_id = trace_id
        _log(module, trace_id, "request_received", method="POST", path=getattr(self, "path", "").split("?", 1)[0], body_bytes=len(body or b""))
        return original_google(self, body, stream, *args, **kwargs) if original_google else None

    def prompt(messages, tools=None, tool_choice=None, *args, **kwargs):
        result = original_prompt(messages, tools, tool_choice, *args, **kwargs)
        trace_id = _trace_id()
        if trace_id:
            prompt_text, images = result
            _log(module, trace_id, "prompt_built", prompt_chars=len(prompt_text or ""), image_count=len(images or []), tool_count=len(tools or []))
        return result

    def parse_calls(text, *args, **kwargs):
        trace_id = _trace_id()
        if trace_id and text:
            _log(module, trace_id, "candidate_tool_call", candidate_chars=len(text))
        clean, calls = original_parse(text, *args, **kwargs)
        if trace_id:
            names = safe_tool_names(calls)
            _log(module, trace_id, "parsed_tool_call", count=len(calls or []), tool_names=names)
            tool_defs, _ = phase4_runtime._current_tool_context()
            if tool_defs:
                errors = validate_tool_calls(calls, tool_defs)
                _log(module, trace_id, "schema_validation", status="pass" if not errors else "fail", error_count=len(errors), tool_names=names)
        return clean, calls

    def generate(*args, **kwargs):
        trace_id = _trace_id()
        if trace_id:
            _log(module, trace_id, "upstream_request", transport="gemini_web")
        started = time.monotonic()
        try:
            raw = original_generate(*args, **kwargs)
            if trace_id:
                _log(module, trace_id, "upstream_response", status="ok", duration_ms=elapsed_ms(started), response_chars=len(raw or ""))
            return raw
        except Exception as exc:
            if trace_id:
                _log(module, trace_id, "upstream_response", status="error", duration_ms=elapsed_ms(started), error_type=type(exc).__name__)
            raise

    def generate_stream(*args, **kwargs):
        trace_id = _trace_id()
        if trace_id:
            _log(module, trace_id, "upstream_request", transport="gemini_web", stream=True)
        started = time.monotonic()
        total = 0
        try:
            for delta in original_stream(*args, **kwargs):
                total += len(delta or "")
                yield delta
            if trace_id:
                _log(module, trace_id, "upstream_response", status="ok", duration_ms=elapsed_ms(started), response_chars=total, stream=True)
        except Exception as exc:
            if trace_id:
                _log(module, trace_id, "upstream_response", status="error", duration_ms=elapsed_ms(started), error_type=type(exc).__name__, stream=True)
            raise

    handler_cls._read_request_body = read_request_body
    handler_cls.do_POST = do_post
    if original_get:
        handler_cls.do_GET = do_get
    if original_chat:
        handler_cls._handle_chat = handle_chat
    if original_responses:
        handler_cls._handle_responses = handle_responses
    if original_google:
        handler_cls._handle_google_generate = handle_google
    if original_prompt:
        module.messages_to_prompt = prompt
    if original_parse:
        module.parse_tool_calls = parse_calls
    if original_generate:
        module.generate = generate
    if original_stream:
        module.generate_stream = generate_stream

    handler_cls._phase10_observability_installed = True
