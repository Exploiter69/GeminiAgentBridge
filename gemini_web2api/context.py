"""Deterministic prompt/context compaction for long agent trajectories."""
from __future__ import annotations

from typing import Any


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return str(content)


def _is_tool_message(message: dict[str, Any]) -> bool:
    return message.get("role") == "tool"


def _is_tool_related(message: dict[str, Any]) -> bool:
    return _is_tool_message(message) or bool(message.get("tool_calls"))


def _message_char_count(message: dict[str, Any]) -> int:
    return len(_content_text(message)) + len(str(message.get("tool_calls", "")))


def _message_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_message_char_count(message) for message in messages)


def _trajectory_groups(messages: list[dict[str, Any]]) -> list[list[int]]:
    """Group assistant tool calls with their following tool results when possible."""
    groups: list[list[int]] = []
    used: set[int] = set()
    for i, message in enumerate(messages):
        if i in used:
            continue
        if message.get("tool_calls"):
            group = [i]
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                group.append(j)
                used.add(j)
                j += 1
            groups.append(group)
            used.add(i)
        elif message.get("role") == "tool":
            groups.append([i])
            used.add(i)
    return groups


def compact_messages(messages: list[dict[str, Any]], max_chars: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compact messages without splitting the newest tool trajectory.

    System instructions and the newest user task are mandatory. Recent
    assistant-tool/result groups are retained atomically. Older messages are
    dropped only when necessary and represented by an explicit marker.
    """
    original_chars = _message_chars(messages)
    if not max_chars or max_chars <= 0 or original_chars <= max_chars:
        return list(messages), {"compacted": False, "elided_messages": 0, "chars": original_chars, "budget": max_chars}

    keep: set[int] = set()
    keep_chars = 0

    def add(index: int) -> None:
        nonlocal keep_chars
        if index not in keep:
            keep.add(index)
            keep_chars += _message_char_count(messages[index])

    # Highest priority: all system contracts.
    for i, message in enumerate(messages):
        if message.get("role") == "system":
            add(i)

    # Current task is never silently removed.
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            add(i)
            break

    # Preserve the newest six coherent tool trajectories, not arbitrary halves.
    groups = _trajectory_groups(messages)
    for group in groups[-6:]:
        for i in group:
            add(i)

    # Fill remaining budget from newest ordinary messages.
    grouped_indices = {i for group in groups for i in group}
    for i in range(len(messages) - 1, -1, -1):
        if i in keep or i in grouped_indices:
            continue
        candidate = keep_chars + _message_char_count(messages[i])
        if candidate <= max_chars:
            add(i)

    selected = sorted(keep)
    elided = len(messages) - len(selected)
    result = [messages[i] for i in selected]
    if elided:
        marker = {"role": "system", "content": f"[ELIDED HISTORY: {elided} older message(s) omitted by context budget]"}
        insert_at = next((n for n, m in enumerate(result) if m.get("role") != "system"), len(result))
        result.insert(insert_at, marker)

    actual_chars = _message_chars(result)
    return result, {
        "compacted": True,
        "elided_messages": elided,
        "chars": actual_chars,
        "budget": max_chars,
        "over_budget": actual_chars > max_chars,
    }
