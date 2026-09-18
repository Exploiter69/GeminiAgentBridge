"""Gemini Web transport implementations."""
import json
import time
import uuid
import re
import urllib.request
import urllib.parse
import urllib.error
import ssl
import os
import hashlib
import threading

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

from .backend import BackendFile, BackendRequest
from .config import CONFIG
from .performance import RetryPolicy
from .backend_selection import effective_backend
from .modern import generate_response as modern_generate_response, generate_stream as modern_generate_stream

_ssl_ctx = None
_cookie_cache = {"str": "", "sapisid": None, "mtime": 0}
_cookie_lock = threading.Lock()
_httpx_client = None
_httpx_client_lock = threading.Lock()



def log(msg: str):
    if CONFIG["log_requests"]:
        import sys
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stderr.flush()


def _get_ssl_ctx():
    global _ssl_ctx
    if _ssl_ctx is None:
        _ssl_ctx = ssl.create_default_context()
    return _ssl_ctx


def _get_httpx_client():
    global _httpx_client
    if _httpx_client is None and HAS_HTTPX:
        with _httpx_client_lock:
            if _httpx_client is None:
                proxy = CONFIG.get("proxy")
                transport = httpx.HTTPTransport(proxy=proxy) if proxy else None
                _httpx_client = httpx.Client(transport=transport, timeout=CONFIG["request_timeout_sec"], verify=True)
    return _httpx_client


def _reset_httpx_client() -> None:
    global _httpx_client
    with _httpx_client_lock:
        client, _httpx_client = _httpx_client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def load_cookie() -> tuple:
    """Load cookie from file with mtime-based caching without logging values."""
    cookie_file = CONFIG.get("cookie_file")
    if not cookie_file or not os.path.exists(cookie_file):
        return "", None
    with _cookie_lock:
        try:
            mtime = os.path.getmtime(cookie_file)
            if mtime == _cookie_cache["mtime"] and _cookie_cache["str"]:
                return _cookie_cache["str"], _cookie_cache["sapisid"]
            with open(cookie_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("{"):
                data = json.loads(content)
                cookie_str = data.get("cookie", "")
                sapisid = data.get("sapisid", "")
                if not cookie_str:
                    pairs = data
                    cookie_str = "; ".join(f"{k}={v}" for k, v in pairs.items() if isinstance(v, str))
                    sapisid = data.get("SAPISID", "")
            else:
                cookie_str = content
                pairs = dict(p.split("=", 1) for p in cookie_str.split("; ") if "=" in p)
                sapisid = pairs.get("SAPISID", "")
            _cookie_cache.update({"str": cookie_str, "sapisid": sapisid or None, "mtime": mtime})
            return cookie_str, sapisid if sapisid else None
        except Exception:
            log("Cookie load error: authentication material could not be parsed")
            return _cookie_cache["str"], _cookie_cache["sapisid"]


def make_sapisidhash(sapisid: str) -> str:
    ts = int(time.time())
    h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{h}"


def _account_prefix() -> str:
    auth_user = CONFIG.get("auth_user")
    if auth_user is None or auth_user == "":
        return ""
    return f"/u/{auth_user}"


def _build_headers() -> dict:
    account_prefix = _account_prefix()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://gemini.google.com",
        "Referer": f"https://gemini.google.com{account_prefix}/app",
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if account_prefix:
        headers["X-Goog-AuthUser"] = str(CONFIG["auth_user"])
    cookie_str, sapisid = load_cookie()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if sapisid:
        headers["Authorization"] = make_sapisidhash(sapisid)
    return headers


def _apply_chat_persistence_flags(inner: list) -> None:
    if CONFIG.get("temporary_chats", False):
        inner[41] = [1]
        inner[45] = 1
    else:
        inner[41] = [2]


def _build_payload(prompt: str, model_id: int, think_mode: int, file_refs: list = None, extra_fields: dict = None) -> str:
    inner = [None] * 102
    if file_refs:
        refs = [[None, None, ref] for ref in file_refs]
        inner[0] = [prompt, 0, None, refs, None, None, 0]
    else:
        inner[0] = [prompt, 0, None, None, None, None, 0]
    inner[1] = ["en"]
    inner[2] = ["", "", "", None, None, None, None, None, None, ""]
    inner[6] = [0]
    inner[7] = 1
    inner[10] = 1
    inner[11] = 0
    inner[17] = [[think_mode]]
    inner[18] = 0
    inner[27] = 1
    inner[30] = [4]
    _apply_chat_persistence_flags(inner)
    inner[53] = 0
    inner[59] = str(uuid.uuid4())
    inner[61] = []
    inner[68] = 1
    inner[79] = model_id
    if extra_fields:
        for k, v in extra_fields.items():
            inner[k] = v
    outer = [None, json.dumps(inner)]
    params = {"f.req": json.dumps(outer)}
    if CONFIG.get("xsrf_token"):
        params["at"] = CONFIG["xsrf_token"]
    return urllib.parse.urlencode(params)


def _get_url() -> str:
    reqid = int(time.time()) % 1000000
    account_prefix = _account_prefix()
    return (
        f"https://gemini.google.com{account_prefix}/_/BardChatUi/data/"
        "assistant.lamda.BardFrontendService/StreamGenerate"
        f"?bl={CONFIG['gemini_bl']}&hl=en&_reqid={reqid}&rt=c"
    )


def clean_text(text: str, strip: bool = True) -> str:
    text = re.sub(r'```(?:python|javascript|text)\?code_(?:reference|stdout)&code_event_index=\d+\n.*?```\n?', '', text, flags=re.DOTALL)
    text = re.sub(r'http://googleusercontent\.com/card_content/\d+\n?', '', text)
    return text.strip() if strip else text


def _extract_texts_from_line(line: str) -> list:
    if '"wrb.fr"' not in line or len(line) < 200:
        return []
    try:
        arr = json.loads(line)
        inner_str = arr[0][2]
        if not inner_str or len(inner_str) < 50:
            return []
        inner = json.loads(inner_str)
        if not (isinstance(inner, list) and len(inner) > 4 and inner[4]):
            return []
        texts = []
        for part in inner[4]:
            if isinstance(part, list) and len(part) > 1 and part[1] and isinstance(part[1], list):
                for t in part[1]:
                    if isinstance(t, str) and t:
                        texts.append(t)
        return texts
    except (json.JSONDecodeError, IndexError, TypeError):
        return []


def extract_response_text(raw: str) -> str:
    bard_err = re.search(r'BardErrorInfo\s*\[(\d+)\]', raw)
    if bard_err:
        raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
    last_text = ""
    for line in raw.splitlines():
        if '"wrb.fr"' not in line:
            continue
        for t in _extract_texts_from_line(line):
            if len(t) > len(last_text):
                last_text = t
    return clean_text(last_text)


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(
        attempts=max(1, int(CONFIG.get("retry_attempts", 3))),
        base_delay_sec=max(0.0, float(CONFIG.get("retry_delay_sec", 2))),
        backoff_multiplier=max(1.0, float(CONFIG.get("retry_backoff_multiplier", 2.0))),
        max_delay_sec=max(0.0, float(CONFIG.get("retry_max_delay_sec", 30.0))),
    )


def _is_retryable_error(error: Exception) -> bool:
    # A provider rate limit is not a transient transport failure. Retrying
    # immediately amplifies the rate limit and can make downstream agents
    # retry the same request repeatedly. Preserve 429 for the API boundary.
    if isinstance(error, urllib.error.HTTPError):
        return error.code in {408, 425} or 500 <= error.code <= 599
    if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return True
    if HAS_HTTPX and isinstance(error, httpx.TransportError):
        return True
    message = str(error)
    if message.startswith("Gemini upstream rejected request:"):
        return False
    return message in {"Gemini upstream returned an empty response", "Gemini stream content changed during retry"}


def _sleep_before_retry(policy: RetryPolicy, attempt: int, error: Exception) -> None:
    delay = policy.delay_for_retry(attempt)
    log(f"Retry {attempt + 1}/{policy.attempts}: {type(error).__name__}; sleeping {delay:g}s")
    if delay:
        time.sleep(delay)


def _legacy_file_refs(files: tuple) -> list[str]:
    if not files:
        return []
    from .multimodal import upload_image
    refs = []
    for item in files:
        data = getattr(item, "data", None)
        filename = getattr(item, "filename", "attachment.bin")
        mime_type = getattr(item, "mime_type", "application/octet-stream")
        if data is None:
            raise ValueError("legacy backend requires file bytes for each attachment")
        refs.append(upload_image(data, filename, mime_type))
    return refs


def _generate_legacy(request: BackendRequest) -> str:
    if not isinstance(request.model, int):
        raise ValueError("legacy backend requires a resolved numeric model mode")
    file_refs = _legacy_file_refs(request.files)
    body = _build_payload(request.prompt, request.model, request.think_mode or 0, file_refs, request.provider_options).encode()
    url = _get_url()
    headers = _build_headers()
    ctx = _get_ssl_ctx()
    proxy = CONFIG.get("proxy")
    policy = _retry_policy()
    last_err = None
    for attempt in range(policy.attempts):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                    urllib.request.HTTPSHandler(context=ctx)
                )
                resp = opener.open(req, timeout=CONFIG["request_timeout_sec"])
            else:
                resp = urllib.request.urlopen(req, context=ctx, timeout=CONFIG["request_timeout_sec"])
            raw = resp.read().decode("utf-8", errors="replace")
            text = extract_response_text(raw)
            if not text:
                raise RuntimeError("Gemini upstream returned an empty response")
            return text
        except Exception as e:
            last_err = e
            if attempt >= policy.attempts - 1 or not _is_retryable_error(e):
                break
            _sleep_before_retry(policy, attempt, e)
    raise last_err


def generate(prompt: str, model_id, think_mode=None, file_refs=None, extra_fields=None) -> str:
    """Generate while preserving every normalized request field."""
    configured_backend = str(CONFIG.get("upstream_backend", "modern")).lower()
    backend = effective_backend(configured_backend, CONFIG.get("cookie_file"))
    request = BackendRequest.from_legacy_args(
        prompt,
        model_id,
        files=file_refs,
        think_mode=think_mode,
        temporary=bool(CONFIG.get("temporary_chats", False)),
        provider_options=extra_fields,
    )
    if backend == "legacy":
        return _generate_legacy(request)
    if backend == "modern":
        return modern_generate_response(request).text
    raise ValueError(f"unsupported upstream_backend: {backend}")


def generate_stream(prompt: str, model_id, think_mode=None, file_refs=None, extra_fields=None):
    """Stream while preserving files/model/temporary/options across transports."""
    configured_backend = str(CONFIG.get("upstream_backend", "modern")).lower()
    backend = effective_backend(configured_backend, CONFIG.get("cookie_file"))
    request = BackendRequest.from_legacy_args(
        prompt,
        model_id,
        stream=True,
        files=file_refs,
        think_mode=think_mode,
        temporary=bool(CONFIG.get("temporary_chats", False)),
        provider_options=extra_fields,
    )
    if backend == "legacy":
        yield from _legacy_stream(request)
        return
    if backend == "modern":
        yield from modern_generate_stream(request)
        return
    raise ValueError(f"unsupported upstream_backend: {backend}")


def _legacy_stream(request: BackendRequest):
    if not HAS_HTTPX:
        text = _generate_legacy(request)
        if text:
            yield text
        return

    if not isinstance(request.model, int):
        raise ValueError("legacy backend requires a resolved numeric model mode")
    file_refs = _legacy_file_refs(request.files)
    body = _build_payload(request.prompt, request.model, request.think_mode or 0, file_refs, request.provider_options)
    url = _get_url()
    headers = _build_headers()
    policy = _retry_policy()
    last_err = None
    emitted_raw_text = ""
    for attempt in range(policy.attempts):
        client = _get_httpx_client()
        try:
            with client.stream("POST", url, content=body, headers=headers) as resp:
                resp.raise_for_status()
                buf = ""
                for chunk in resp.iter_text():
                    buf += chunk
                    if "BardErrorInfo" in buf:
                        bard_err = re.search(r'BardErrorInfo\s*\[(\d+)\]', buf)
                        if bard_err:
                            raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        for t in _extract_texts_from_line(line):
                            if t == emitted_raw_text or emitted_raw_text.startswith(t):
                                continue
                            if not t.startswith(emitted_raw_text):
                                raise RuntimeError("Gemini stream content changed during retry")
                            delta = clean_text(t[len(emitted_raw_text):], strip=False)
                            emitted_raw_text = t
                            if delta:
                                yield delta
            return
        except Exception as e:
            last_err = e
            if attempt >= policy.attempts - 1 or not _is_retryable_error(e):
                break
            if HAS_HTTPX and httpx is not None and isinstance(e, httpx.TransportError):
                _reset_httpx_client()
            _sleep_before_retry(policy, attempt, e)
    raise last_err
