"""Multimodal: safe remote-image fetching and Gemini image upload."""
import base64
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from .config import CONFIG
from .gemini import load_cookie, make_sapisidhash, _get_ssl_ctx, log


class UploadedFileRef(str):
    """String-compatible legacy file reference carrying modern backend bytes."""

    def __new__(cls, reference: str, data: bytes, mime_type: str, filename: str):
        obj = super().__new__(cls, reference)
        obj.data = data
        obj.mime_type = mime_type
        obj.filename = filename
        return obj


def _get_page_tokens() -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    cookie_str, sapisid = load_cookie()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if sapisid:
        headers["Authorization"] = make_sapisidhash(sapisid)
    try:
        req = urllib.request.Request("https://gemini.google.com/app", headers=headers)
        proxy = CONFIG.get("proxy")
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                urllib.request.HTTPSHandler(context=_get_ssl_ctx()),
            )
            resp = opener.open(req, timeout=30)
        else:
            resp = urllib.request.urlopen(req, context=_get_ssl_ctx(), timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
        tokens = {}
        for key, pattern in [
            ("push_id", r'"qKIAYe":"([^"]+)"'),
            ("pctx", r'"Ylro7b":"([^"]+)"'),
            ("at", r'"thykhd":"([^"]+)"'),
        ]:
            match = re.search(pattern, html)
            if match:
                tokens[key] = match.group(1)
        return tokens
    except Exception:
        log("Page token fetch failed")
        return {}


_page_tokens_cache = {"tokens": {}, "ts": 0}
_page_tokens_lock = threading.Lock()


def _cached_page_tokens() -> dict:
    now = time.time()
    with _page_tokens_lock:
        if now - _page_tokens_cache["ts"] <= 600 and _page_tokens_cache["tokens"]:
            return dict(_page_tokens_cache["tokens"])
        tokens = _get_page_tokens()
        _page_tokens_cache["tokens"] = tokens
        _page_tokens_cache["ts"] = now
        return dict(tokens)


def detect_image_mime(image_bytes: bytes, fallback: str = "image/png") -> str:
    if not isinstance(image_bytes, bytes):
        return fallback
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"BM"):
        return "image/bmp"
    if image_bytes.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(image_bytes) >= 12 and image_bytes[4:8] == b"ftyp":
        brand = image_bytes[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return "image/heic"
    return fallback


def _resolve_public_host(hostname: str) -> None:
    if not hostname:
        raise ValueError("image URL has no hostname")
    try:
        direct = ipaddress.ip_address(hostname)
        addresses = [direct]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("image URL hostname could not be resolved") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    if not addresses:
        raise ValueError("image URL hostname could not be resolved")
    for address in addresses:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise ValueError("image URL target is not a public address")


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("image URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("image URL credentials are not allowed")
    _resolve_public_host(parsed.hostname or "")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _image_opener():
    proxy = CONFIG.get("proxy")
    handlers = [_SafeRedirectHandler(), urllib.request.HTTPSHandler(context=_get_ssl_ctx())]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def upload_image(image_bytes: bytes, filename: str = "image.png", mime_type: str = "image/png") -> str:
    """Upload for legacy transport, or retain bytes for the modern client."""
    max_bytes = int(CONFIG.get("max_image_bytes", 10 * 1024 * 1024))
    if not isinstance(image_bytes, bytes) or len(image_bytes) > max_bytes:
        raise ValueError("image exceeds configured size limit")

    # gemini-webapi accepts local files, so the modern path must not perform a
    # legacy Gemini upload and then throw the resulting reference away.
    if str(CONFIG.get("upstream_backend", "modern")).lower() != "legacy":
        return UploadedFileRef(
            f"/agentbridge/local/{filename}", image_bytes, mime_type, filename
        )

    tokens = _cached_page_tokens()
    push_id = tokens.get("push_id", "feeds/mcudyrk2a4khkz")
    pctx = tokens.get("pctx", "CgcSBWjK7pYx")
    cookie_str, sapisid = load_cookie()
    ctx = _get_ssl_ctx()
    proxy = CONFIG.get("proxy")
    start_headers = {
        "Push-ID": push_id,
        "X-Tenant-Id": "bard-storage",
        "X-Client-Pctx": pctx,
        "X-Goog-Upload-Header-Content-Length": str(len(image_bytes)),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if cookie_str:
        start_headers["Cookie"] = cookie_str
    if sapisid:
        start_headers["Authorization"] = make_sapisidhash(sapisid)

    start_url = "https://content-push.googleapis.com/upload/"
    req = urllib.request.Request(start_url, data=b"", headers=start_headers, method="POST")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
            urllib.request.HTTPSHandler(context=ctx),
        )
        resp = opener.open(req, timeout=30)
    else:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)

    upload_url = resp.headers.get("X-Goog-Upload-URL") or resp.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Gemini upload session did not return an upload URL")
    log("Upload session started")
    upload_headers = {
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Type": "application/octet-stream",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    req2 = urllib.request.Request(upload_url, data=image_bytes, headers=upload_headers, method="POST")
    if proxy:
        resp2 = opener.open(req2, timeout=60)
    else:
        resp2 = urllib.request.urlopen(req2, context=ctx, timeout=60)
    file_ref = resp2.read().decode("utf-8", errors="replace").strip()
    if not file_ref or not file_ref.startswith("/"):
        raise RuntimeError("Gemini upload returned an invalid file reference")
    log(f"Image uploaded: {filename}")
    return file_ref


def fetch_image_bytes(url: str) -> bytes:
    """Fetch a remote image with SSRF and size protections."""
    _validate_remote_url(url)
    max_bytes = int(CONFIG.get("max_image_bytes", 10 * 1024 * 1024))
    opener = _image_opener()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=30) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError("remote image exceeds configured size limit")
                except ValueError as exc:
                    if str(exc) == "remote image exceeds configured size limit":
                        raise
            chunks = []
            total = 0
            while True:
                chunk = resp.read(min(64 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("remote image exceeds configured size limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except ValueError:
        raise
    except Exception as exc:
        log(f"Image fetch failed: {type(exc).__name__}")
        return b""
