"""Deterministic prompt/context compaction for long agent trajectories."""
from __future__ import annotations

from typing import Any


SECTION_ORDER = ("system", "task", "current", "recent_tools", "older", "elided")


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return str(content)


def _is_tool_message(message: dict[str, Any]) -> bool:
    return message.get("role") == "tool"


def _is_tool_related(message: dict[str, Any]) -> bool:
    return _is_tool_message(message) or bool(message.get("tool_calls"))


def compact_messages(messages: list[dict[str, Any]], max_chars: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compact messages while preserving task identity and recent tool state.

    The function never invents or summarizes tool results. If a message does
    not fit, it is removed and represented only by an explicit elision marker.
    ``max_chars=None`` or a non-positive budget disables compaction.
    """
    if not max_chars or max_chars <= 0:
        return list(messages), {"compacted": False, "elided_messages": 0, "chars": _message_chars(messages)}
    if _message_chars(messages) <= max_chars:
        return list(messages), {"compacted": False, "elided_messages": 0, "chars": _message_chars(messages)}

    indexed = list(enumerate(messages))
    keep: set[int] = set()

    # Contract/system messages are highest priority.
    keep.update(i for i, m in indexed if m.get("role") == "system")

    # Preserve the newest user message as the current task.
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            keep.add(i)
            break

    # Preserve the newest tool call/result pairs and their immediate assistant
    # messages. This is deliberately recency-based and does not fabricate a
    # summary when older content is removed.
    recent_related = [i for i, m in indexed if _is_tool_related(m)]
    keep.update(recent_related[-6:])
    for i in list(keep):
        if i > 0 and _is_tool_related(messages[i]):
            keep.add(i - 1)

    # Fill remaining budget from newest messages first, without splitting a
    # message or changing its contents.
    for i in range(len(messages) - 1, -1, -1):
        if i in keep:
            continue
        candidate = sorted(keep | {i})
        if _message_chars([messages[j] for j in candidate]) <= max_chars:
            keep.add(i)

    selected = sorted(keep)
    elided = len(messages) - len(selected)
    result = [messages[i] for i in selected]
    if elided:
        marker = {
            "role": "system",
            "content": f"[ELIDED HISTORY: {elided} older message(s) omitted by context budget]",
        }
        insert_at = next((n for n, m in enumerate(result) if m.get("role") != "system"), len(result))
        result.insert(insert_at, marker)

    return result, {
        "compacted": True,
        "elided_messages": elided,
        "chars": _message_chars(result),
        "budget": max_chars,
    }


def _message_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += len(_content_text(message))
        total += len(str(message.get("tool_calls", "")))
    return total
