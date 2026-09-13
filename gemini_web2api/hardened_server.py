"""Hardened HTTP boundary layered on the protocol handler."""
from __future__ import annotations

import itertools
import json
import time
import urllib.parse
import uuid

from .config import CONFIG
from .gemini import generate_stream, log
from .security import RequestBodyTooLarge, constant_time_equal, public_error
from .server import GeminiHandler, ThreadedServer, _upload_images
from .tools import google_contents_to_prompt, messages_to_prompt
from .models import resolve_model


class HardenedGeminiHandler(GeminiHandler):
    """OpenAI/Google handler with explicit security and streaming invariants."""

    def _is_api_path(self) -> bool:
        return self.path.startswith("/v1") or self.path.startswith("/v1beta")

    def _authorized(self):
        keys = [str(k) for k in (CONFIG.get("api_keys") or []) if str(k)]
        if not keys:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
            if any(constant_time_equal(presented, key) for key in keys):
                return True
        for header in ("x-api-key", "x-goog-api-key"):
            presented = self.headers.get(header, "")
            if any(constant_time_equal(presented, key) for key in keys):
                return True
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        presented = query.get("key", [""])[0]
        return any(constant_time_equal(presented, key) for key in keys)

    def send_json(self, data, status=200):
        if status >= 500:
            data = {"error": {"message": public_error(status)}}
        super().send_json(data, status)

    def _read_request_body(self) -> bytes:
        max_bytes = max(1, int(CONFIG.get("max_request_body_bytes", 4 * 1024 * 1024)))
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        if "chunked" in transfer_encoding.lower():
            chunks = []
            total = 0
            while True:
                size_line = self.rfile.readline(64)
                if not size_line:
                    raise ValueError("invalid chunked request body")
                size_text = size_line.split(b";", 1)[0].strip()
                try:
                    size = int(size_text, 16)
                except ValueError as exc:
                    raise ValueError("invalid chunked request body") from exc
                if size < 0:
                    raise ValueError("invalid chunked request body")
                if size == 0:
                    while True:
                        trailer = self.rfile.readline(8192)
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                if total + size > max_bytes:
                    raise RequestBodyTooLarge()
                chunk = self.rfile.read(size)
                if len(chunk) != size:
                    raise ValueError("truncated chunked request body")
                if self.rfile.read(2) != b"\r\n":
                    raise ValueError("invalid chunked request body")
                chunks.append(chunk)
                total += size
            return b"".join(chunks)

        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            return b""
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 0:
            raise ValueError("invalid content length")
        if length > max_bytes:
            raise RequestBodyTooLarge()
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("truncated request body")
        return body

    def _safe_stream_error(self, event: str = "error"):
        payload = {"error": {"message": "upstream stream failed"}}
        try:
            if event == "event":
                self.wfile.write(b"event: error\n")
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _stream_chat_safely(self, prompt, model_id, think_mode, file_refs, extra_fields, model_name, cid):
        stream = generate_stream(prompt, model_id, think_mode, file_refs, extra_fields)
        committed = False
        try:
            first = next(stream)
            if not first:
                raise RuntimeError("empty upstream stream")
            self._start_sse()
            committed = True
            role_chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_name, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(role_chunk)}\n\n".encode())
            first_chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_name, "choices": [{"index": 0, "delta": {"content": first}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            for delta in stream:
                if not delta:
                    continue
                chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_name, "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            end = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_name, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(end)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log("OpenAI stream client disconnected")
        except Exception as exc:
            log(f"OpenAI stream failed: {type(exc).__name__}")
            if committed:
                self._safe_stream_error()
            else:
                self.send_json({"error": {"message": public_error(502)}}, 502)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _stream_google_safely(self, prompt, model_id, think_mode, file_refs, extra_fields, model_name):
        stream = generate_stream(prompt, model_id, think_mode, file_refs, extra_fields)
        committed = False
        try:
            first = next(stream)
            if not first:
                raise RuntimeError("empty upstream stream")
            self._start_sse()
            committed = True
            for delta in itertools.chain((first,), stream):
                if not delta:
                    continue
                chunk_obj = {"candidates": [{"content": {"parts": [{"text": delta}], "role": "model"}, "index": 0}], "modelVersion": model_name}
                self.wfile.write(f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            final = {"candidates": [{"finishReason": "STOP", "index": 0}], "modelVersion": model_name}
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log("Google stream client disconnected")
        except Exception as exc:
            log(f"Google stream failed: {type(exc).__name__}")
            if committed:
                self._safe_stream_error(event="event")
            else:
                self.send_json({"error": {"message": public_error(502)}}, 502)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _handle_chat(self, body: bytes):
        req = self._parse_body(body)
        if isinstance(req, dict) and req.get("stream") and (not req.get("tools") or req.get("tool_choice", "auto") == "none"):
            model_name, model_id, think_mode, err, extra_fields = resolve_model(req.get("model", CONFIG["default_model"]))
            if err:
                self.send_json({"error": {"message": err}}, 400)
                return
            prompt, images = messages_to_prompt(req.get("messages", []), req.get("tools"), req.get("tool_choice", "auto"))
            if not prompt.strip():
                self.send_json({"error": {"message": "empty prompt"}}, 400)
                return
            try:
                file_refs = _upload_images(images)
            except Exception:
                self.send_json({"error": {"message": public_error(502)}}, 502)
                return
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            self._stream_chat_safely(prompt, model_id, think_mode, file_refs, extra_fields, model_name, cid)
            return
        return super()._handle_chat(body)

    def _handle_google_generate(self, body: bytes, stream: bool):
        if stream:
            req = self._parse_body(body)
            if isinstance(req, dict):
                model_path = self.path.split("/v1beta/models/", 1)[-1].split(":", 1)[0]
                model_name, model_id, think_mode, err, extra_fields = resolve_model(model_path or CONFIG["default_model"])
                if err:
                    self.send_json({"error": {"message": err}}, 400)
                    return
                tool_config = req.get("toolConfig", {})
                mode = tool_config.get("functionCallingConfig", {}).get("mode", "AUTO")
                if not req.get("tools") or mode == "NONE":
                    prompt, images = google_contents_to_prompt(req)
                    if not prompt.strip():
                        self.send_json({"error": {"message": "empty content"}}, 400)
                        return
                    try:
                        file_refs = _upload_images(images)
                    except Exception:
                        self.send_json({"error": {"message": public_error(502)}}, 502)
                        return
                    self._stream_google_safely(prompt, model_id, think_mode, file_refs, extra_fields, model_name)
                    return
        return super()._handle_google_generate(body, stream)

    def do_GET(self):
        if self._is_api_path() and not self._authorized():
            self.send_json({"error": {"message": public_error(401)}}, 401)
            return
        return super().do_GET()

    def do_POST(self):
        try:
            if self._is_api_path() and not self._authorized():
                self.send_json({"error": {"message": public_error(401)}}, 401)
                return
            body = self._read_request_body()
            if self.path == "/v1/chat/completions":
                self._handle_chat(body)
            elif self.path == "/v1/responses":
                self._handle_responses(body)
            elif ":streamGenerateContent" in self.path:
                self._handle_google_generate(body, stream=True)
            elif ":generateContent" in self.path:
                self._handle_google_generate(body, stream=False)
            else:
                self.send_json({"error": {"message": "not found"}}, 404)
        except RequestBodyTooLarge:
            self.send_json({"error": {"message": public_error(413)}}, 413)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log(f"POST error: {type(exc).__name__}")
            try:
                self.send_json({"error": {"message": public_error(500)}}, 500)
            except (BrokenPipeError, ConnectionResetError):
                pass


class HardenedThreadedServer(ThreadedServer):
    """Threaded HTTP server with explicit daemon-thread shutdown semantics."""
    daemon_threads = True
    allow_reuse_address = True
