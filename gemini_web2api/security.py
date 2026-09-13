"""Security policy helpers for the HTTP boundary."""
from __future__ import annotations

import ipaddress
import hmac


class RequestBodyTooLarge(ValueError):
    """Raised when an HTTP request exceeds the configured body limit."""


def is_loopback_bind(host: str) -> bool:
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind(host: str, api_keys: list[str] | None) -> None:
    """Refuse unauthenticated non-loopback listeners."""
    if is_loopback_bind(host):
        return
    if not api_keys:
        raise ValueError("remote binding requires at least one API key")


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left), str(right))


def public_error(status: int) -> str:
    """Return a deliberately non-sensitive client-facing message."""
    return {
        400: "invalid request",
        401: "invalid api key",
        403: "request forbidden",
        413: "request body too large",
        429: "upstream rate limit",
        502: "upstream request failed",
        503: "upstream service unavailable",
        504: "upstream request timed out",
    }.get(status, "internal server error")
