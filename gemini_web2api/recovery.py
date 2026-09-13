"""Bounded recovery and explicit error semantics for Phase 5.

This module is deliberately independent of HTTP, Gemini, and downstream tool
execution.  It classifies failures, decides whether retry is safe, and keeps
failed observations distinguishable from successful empty results.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class ErrorType(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    USAGE_LIMIT = "usage_limit"
    AUTHENTICATION = "authentication"
    SESSION = "session"
    EMPTY_RESPONSE = "empty_response"
    MALFORMED_TOOL_CALL = "malformed_tool_call"
    INVALID_TOOL_SCHEMA = "invalid_tool_schema"
    MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
    TOOL_RESULT_ERROR = "tool_result_error"
    UNKNOWN = "unknown"


_RETRYABLE = {
    ErrorType.TIMEOUT,
    ErrorType.RATE_LIMIT,
    ErrorType.USAGE_LIMIT,
    ErrorType.EMPTY_RESPONSE,
}

_REPAIRABLE = {
    ErrorType.MALFORMED_TOOL_CALL,
    ErrorType.INVALID_TOOL_SCHEMA,
    ErrorType.MISSING_REQUIRED_ARGUMENT,
}


@dataclass(frozen=True)
class Failure:
    """A classified failure safe to expose in diagnostics."""

    error_type: ErrorType
    message: str
    status_code: int | None = None
    retry_after: float | None = None

    @property
    def retryable(self) -> bool:
        return self.error_type in _RETRYABLE

    @property
    def repairable(self) -> bool:
        return self.error_type in _REPAIRABLE

    def public(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "error",
            "error_type": self.error_type.value,
            "message": self.message,
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        return result


@dataclass(frozen=True)
class RetryResult:
    value: Any = None
    failure: Failure | None = None
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.failure is None


def classify_http_status(status: int) -> ErrorType:
    if status in (408, 504):
        return ErrorType.TIMEOUT
    if status == 429:
        return ErrorType.RATE_LIMIT
    if status in (401, 403):
        return ErrorType.AUTHENTICATION
    if status in (409, 425, 500, 502, 503):
        return ErrorType.SESSION if status == 503 else ErrorType.UNKNOWN
    return ErrorType.UNKNOWN


def classify_exception(exc: BaseException) -> Failure:
    """Classify transport/upstream exceptions without leaking sensitive values."""
    import socket
    import urllib.error

    if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        return Failure(ErrorType.TIMEOUT, "upstream request timed out")

    if isinstance(exc, urllib.error.HTTPError):
        status = int(exc.code)
        error_type = classify_http_status(status)
        if status == 429:
            return Failure(error_type, "upstream rate limit", status)
        if status in (401, 403):
            return Failure(error_type, "upstream authentication/session rejected", status)
        if status in (408, 504):
            return Failure(error_type, "upstream timeout", status)
        return Failure(error_type, "upstream HTTP error", status)

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timed out" in message:
        return Failure(ErrorType.TIMEOUT, "upstream request timed out")
    if "rate" in message and "limit" in message:
        return Failure(ErrorType.RATE_LIMIT, "upstream rate limit")
    if "usage" in message and "limit" in message:
        return Failure(ErrorType.USAGE_LIMIT, "upstream usage limit")
    if "empty response" in message:
        return Failure(ErrorType.EMPTY_RESPONSE, "upstream returned an empty response")
    return Failure(ErrorType.UNKNOWN, "upstream request failed")


def classify_upstream_text(raw: str) -> Failure | None:
    """Classify known Gemini error markers without returning raw upstream data."""
    if not raw or not raw.strip():
        return Failure(ErrorType.EMPTY_RESPONSE, "upstream returned an empty response")
    lowered = raw.lower()
    if "barderrorinfo" in lowered:
        if "429" in lowered or "rate" in lowered and "limit" in lowered:
            return Failure(ErrorType.RATE_LIMIT, "Gemini upstream rate limit")
        if "usage" in lowered and "limit" in lowered:
            return Failure(ErrorType.USAGE_LIMIT, "Gemini upstream usage limit")
        if "401" in lowered or "403" in lowered or "unauthorized" in lowered:
            return Failure(ErrorType.AUTHENTICATION, "Gemini upstream authentication/session rejected")
        return Failure(ErrorType.UNKNOWN, "Gemini upstream rejected the request")
    return None


def retry_delay(base_delay: float, attempt: int, retry_after: float | None = None, cap: float = 30.0) -> float:
    """Return bounded exponential backoff; server hints are also capped."""
    delay = float(base_delay) * (2 ** max(0, attempt - 1))
    if retry_after is not None:
        delay = max(delay, float(retry_after))
    return min(max(0.0, delay), float(cap))


def run_with_recovery(
    operation: Callable[[], Any],
    attempts: int,
    delay_sec: float,
    classify: Callable[[BaseException], Failure] = classify_exception,
    sleeper: Callable[[float], None] | None = None,
) -> RetryResult:
    """Run a retryable operation with a strict attempt bound."""
    import time

    max_attempts = max(1, int(attempts))
    sleep = sleeper or time.sleep
    last_failure: Failure | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return RetryResult(value=operation(), attempts=attempt)
        except Exception as exc:  # operation boundary: classify, never fabricate
            failure = classify(exc)
            last_failure = failure
            if not failure.retryable or attempt >= max_attempts:
                return RetryResult(failure=failure, attempts=attempt)
            sleep(retry_delay(delay_sec, attempt, failure.retry_after))

    return RetryResult(failure=last_failure or Failure(ErrorType.UNKNOWN, "operation failed"), attempts=max_attempts)


def failed_tool_observation(
    tool_name: str,
    error_type: ErrorType | str,
    message: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Create an explicit failed observation; never represent it as success."""
    value = error_type.value if isinstance(error_type, ErrorType) else str(error_type)
    result: dict[str, Any] = {
        "status": "error",
        "error_type": value,
        "tool": tool_name,
        "message": message,
    }
    result.update(metadata)
    return result


def is_failed_tool_observation(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "error" and bool(value.get("error_type"))


def preserve_tool_observation(value: Any) -> Any:
    """Return tool observations unchanged; only explicit errors are classified."""
    if is_failed_tool_observation(value):
        return dict(value)
    return value
