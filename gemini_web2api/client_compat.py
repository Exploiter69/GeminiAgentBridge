"""Compatibility contract for real agent clients.

Phase 8 deliberately keeps client execution outside the bridge.  This module
contains the small, deterministic contract used by the compatibility harness:
request shapes expected from Hermes/OpenCode and checks for client-visible
OpenAI-compatible responses.  It never executes filesystem or shell tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompatibilityCase:
    name: str
    prompt: str
    required_tools: tuple[str, ...]
    artifact: str | None = None


COMPATIBILITY_MATRIX = (
    CompatibilityCase("list_files", "List the files in the current working directory.", ("list_files",)),
    CompatibilityCase("read_file", "Read sample.txt and report its contents.", ("read_file",), "sample.txt"),
    CompatibilityCase("create_file", "Create created.txt containing PHASE8_CREATE_OK.", ("write_file",), "created.txt"),
    CompatibilityCase("edit_file", "Edit sample.txt so it contains PHASE8_EDIT_OK.", ("edit_file",), "sample.txt"),
    CompatibilityCase("terminal", "Run a terminal command that prints PHASE8_TERMINAL_OK.", ("terminal",)),
    CompatibilityCase("search_then_read", "Search for sample.txt, then read it.", ("search", "read_file"), "sample.txt"),
    CompatibilityCase("search_then_edit", "Search for sample.txt, then edit it.", ("search", "edit_file"), "sample.txt"),
    CompatibilityCase("multi_step", "List files, read sample.txt, then create summary.txt.", ("list_files", "read_file", "write_file"), "summary.txt"),
    CompatibilityCase("test_execution", "Run the test command and report its result.", ("terminal",)),
    CompatibilityCase("git_status", "Show git status.", ("git_status",)),
    CompatibilityCase("git_diff", "Show git diff.", ("git_diff",)),
    CompatibilityCase("explicit_workdir", "Work only in the current working directory and read sample.txt.", ("read_file",), "sample.txt"),
    CompatibilityCase("long_task", "Perform a long multi-step task while preserving the current workspace and final state.", ("list_files", "read_file", "terminal", "write_file")),
)


def validate_chat_completion(payload: dict[str, Any]) -> list[str]:
    """Return protocol errors for a non-streaming chat completion."""
    errors: list[str] = []
    if payload.get("object") != "chat.completion":
        errors.append("object is not chat.completion")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        errors.append("choices is missing or empty")
        return errors
    choice = choices[0]
    if choice.get("finish_reason") not in {"stop", "tool_calls"}:
        errors.append("unsupported finish_reason")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        errors.append("assistant message is missing")
    if choice.get("finish_reason") == "tool_calls":
        calls = message.get("tool_calls") if isinstance(message, dict) else None
        if not isinstance(calls, list) or not calls:
            errors.append("tool_calls finish without tool_calls")
        else:
            for call in calls:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                if call.get("type") != "function":
                    errors.append("tool call type is not function")
                if not fn.get("name"):
                    errors.append("tool call has no function name")
                if "arguments" not in fn:
                    errors.append("tool call has no arguments field")
    return errors


def validate_models_response(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("object") != "list":
        errors.append("models object is not list")
    if not isinstance(payload.get("data"), list) or not payload["data"]:
        errors.append("models data is missing or empty")
    return errors


def case_names() -> tuple[str, ...]:
    return tuple(case.name for case in COMPATIBILITY_MATRIX)
