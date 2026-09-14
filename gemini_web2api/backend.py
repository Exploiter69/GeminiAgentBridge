"""Backend-neutral request/response contracts.

The HTTP adapters must not silently drop provider capabilities while translating
OpenAI/Google requests to a concrete Gemini Web transport.  This module is the
single internal contract between the protocol layer and backends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class BackendFile:
    """A file supplied by the caller before a backend chooses its upload path."""

    data: bytes
    mime_type: str = "application/octet-stream"
    filename: str = "attachment.bin"


@dataclass(frozen=True)
class BackendRequest:
    """Complete normalized generation request.

    ``provider_options`` is deliberately opaque: fields understood by the
    legacy StreamGenerate transport can travel through the modern-independent
    layer without being silently discarded.
    """

    prompt: str
    model: str
    stream: bool = False
    files: tuple[BackendFile, ...] = ()
    think_mode: int | None = None
    temporary: bool = False
    provider_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy_args(
        cls,
        prompt: str,
        model: str,
        *,
        stream: bool = False,
        files: Iterable[BackendFile] | None = None,
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


@dataclass(frozen=True)
class BackendResponse:
    """Normalized backend result while retaining provider metadata."""

    text: str
    thoughts: str = ""
    metadata: Any = None
    raw: Any = None


class BackendCapabilityError(RuntimeError):
    """Raised when a requested capability cannot be represented safely."""
