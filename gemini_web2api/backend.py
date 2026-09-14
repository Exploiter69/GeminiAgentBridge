"""Backend-neutral request/response contracts.

The HTTP adapters must not silently drop provider capabilities while translating
OpenAI/Google requests to a concrete Gemini Web transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


@dataclass(frozen=True)
class BackendFile:
    """A file supplied by the caller before a backend chooses its upload path."""

    data: bytes
    mime_type: str = "application/octet-stream"
    filename: str = "attachment.bin"


@dataclass(frozen=True)
class BackendRequest:
    """Complete normalized generation request passed to a concrete backend."""

    prompt: str
    model: str | int
    stream: bool = False
    files: tuple[BackendFile | str, ...] = ()
    think_mode: int | None = None
    temporary: bool = False
    provider_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy_args(
        cls,
        prompt: str,
        model: str | int,
        *,
        stream: bool = False,
        files: Iterable[BackendFile | str] | None = None,
        think_mode: int | None = None,
        temporary: bool = False,
        provider_options: dict[str, Any] | None = None,
    ) -> "BackendRequest":
        return cls(
            prompt=prompt,
            model=model,
            stream=stream,
            files=tuple(files or ()),
            think_mode=think_mode,
            temporary=temporary,
            provider_options=dict(provider_options or {}),
        )


@dataclass(frozen=True)
class BackendCapabilities:
    """Capabilities exposed by a concrete transport."""

    files: bool
    streaming: bool
    dynamic_models: bool
    thoughts: bool
    temporary: bool
    provider_options: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "files": self.files,
            "streaming": self.streaming,
            "dynamic_models": self.dynamic_models,
            "thoughts": self.thoughts,
            "temporary": self.temporary,
            "provider_options": self.provider_options,
        }


class BackendHealthState(str, Enum):
    """Lifecycle state reported by a backend without exposing credentials."""

    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True)
class BackendHealth:
    """Safe health snapshot for diagnostics/readiness checks."""

    state: BackendHealthState
    initialized: bool = False
    authenticated: bool = False
    model_catalog: bool = False
    last_error: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == BackendHealthState.READY and self.initialized and self.authenticated

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "initialized": self.initialized,
            "authenticated": self.authenticated,
            "model_catalog": self.model_catalog,
            "ready": self.ready,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class BackendResponse:
    """Normalized backend result while retaining provider metadata."""

    text: str
    thoughts: str = ""
    metadata: Any = None
    raw: Any = None


class BackendCapabilityError(RuntimeError):
    """Raised when a requested capability cannot be represented safely."""


class BackendProtocol:
    """Interface implemented by modern and legacy transports."""

    capabilities: BackendCapabilities

    def health(self) -> BackendHealth:
        raise NotImplementedError

    def resolve_model(self, requested: str) -> Any:
        raise NotImplementedError

    def generate_response(self, request: BackendRequest) -> BackendResponse:
        raise NotImplementedError

    def generate_stream_response(self, request: BackendRequest):
        raise NotImplementedError

    def shutdown(self) -> None:
        raise NotImplementedError
