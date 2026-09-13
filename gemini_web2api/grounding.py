"""Explicit workspace/task grounding facts.

Grounding is advisory state supplied by the downstream agent/client.  The
bridge never probes the filesystem here and never infers a working directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GroundingFacts:
    requested_cwd: str | None = None
    runtime_cwd: str | None = None
    task_target: str | None = None
    known_files: tuple[str, ...] = field(default_factory=tuple)
    open_files: tuple[str, ...] = field(default_factory=tuple)
    last_tool_call: dict[str, Any] | None = None
    last_tool_result: dict[str, Any] | None = None

    @classmethod
    def from_request(cls, request: dict[str, Any] | None) -> "GroundingFacts":
        """Read only explicit grounding supplied by a client.

        Accepted locations are ``metadata.grounding`` and top-level
        ``grounding``. Unknown/malformed values are ignored rather than
        guessed. Tool call/result payloads are retained as opaque structured
        observations and are never executed by the bridge.
        """
        if not isinstance(request, dict):
            return cls()
        raw = request.get("grounding")
        if raw is None and isinstance(request.get("metadata"), dict):
            raw = request["metadata"].get("grounding")
        if not isinstance(raw, dict):
            return cls()

        def text(name: str) -> str | None:
            value = raw.get(name)
            return value if isinstance(value, str) and value else None

        def strings(name: str) -> tuple[str, ...]:
            value = raw.get(name, ())
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(v for v in value if isinstance(v, str) and v)

        def mapping(name: str) -> dict[str, Any] | None:
            value = raw.get(name)
            return dict(value) if isinstance(value, dict) else None

        return cls(
            requested_cwd=text("requested_cwd"),
            runtime_cwd=text("runtime_cwd"),
            task_target=text("task_target"),
            known_files=strings("known_files"),
            open_files=strings("open_files"),
            last_tool_call=mapping("last_tool_call"),
            last_tool_result=mapping("last_tool_result"),
        )

    @property
    def is_explicit(self) -> bool:
        return any((
            self.requested_cwd,
            self.runtime_cwd,
            self.task_target,
            self.known_files,
            self.open_files,
            self.last_tool_call,
            self.last_tool_result,
        ))

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_cwd": self.requested_cwd,
            "runtime_cwd": self.runtime_cwd,
            "task_target": self.task_target,
            "known_files": list(self.known_files),
            "open_files": list(self.open_files),
            "last_tool_call": self.last_tool_call,
            "last_tool_result": self.last_tool_result,
        }

    def to_prompt(self) -> str:
        """Render explicit facts for the model without inventing missing data."""
        if not self.is_explicit:
            return ""
        return (
            "# Grounding facts\n"
            "These are explicit observations supplied by the agent runtime. "
            "Do not invent filesystem facts. If a fact is absent, treat it as unknown.\n"
            f"{self._line('requested_cwd', self.requested_cwd)}"
            f"{self._line('runtime_cwd', self.runtime_cwd)}"
            f"{self._line('task_target', self.task_target)}"
            f"{self._line_list('known_files', self.known_files)}"
            f"{self._line_list('open_files', self.open_files)}"
            f"{self._line_mapping('last_tool_call', self.last_tool_call)}"
            f"{self._line_mapping('last_tool_result', self.last_tool_result)}"
        ).rstrip()

    @staticmethod
    def _line(name: str, value: str | None) -> str:
        return f"- {name}: {value}\n" if value else ""

    @staticmethod
    def _line_list(name: str, value: tuple[str, ...]) -> str:
        return f"- {name}: {list(value)}\n" if value else ""

    @staticmethod
    def _line_mapping(name: str, value: dict[str, Any] | None) -> str:
        return f"- {name}: {value}\n" if value else ""
