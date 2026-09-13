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


def _message_char_count(message: dict[str, Any]) -> int:
    return len(_content_text(message)) + len(str(message.get("tool_calls", "")))


def compact_messages(messages: list[dict[str, Any]], max_chars: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compact messages while preserving task identity and recent tool state.

    The function never invents or summarizes tool results. If a message does
    not fit, it is removed and represented only by an explicit elision marker.
    ``max_chars=None`` or a non-positive budget disables compaction.

    Phase 12 keeps the same selection policy as the original implementation,
    but tracks the retained character count incrementally instead of repeatedly
    serializing/sorting the retained set for every candidate.
    """
    original_chars = _message_chars(messages)
    if not max_chars or max_chars <= 0:
        return list(messages), {"compacted": False, "elided_messages": 0, "chars": original_chars}
    if original_chars <= max_chars:
        return list(messages), {"compacted": False, "elided_messages": 0, "chars": original_chars}

    indexed = list(enumerate(messages))
    keep: set[int] = set()
    keep_chars = 0

    def add(index: int) -> None:
        nonlocal keep_chars
        if index not in keep:
            keep.add(index)
            keep_chars += _message_char_count(messages[index])

    # Contract/system messages are highest priority.
    for i, message in indexed:
        if message.get("role") == "system":
            add(i)

    # Preserve the newest user message as the current task.
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            add(i)
            break

    # Preserve the newest tool call/result pairs and their immediate assistant
    # messages. This is deliberately recency-based and does not fabricate a
    # summary when older content is removed.
    recent_related = [i for i, m in indexed if _is_tool_related(m)]
    for i in recent_related[-6:]:
        add(i)
    for i in tuple(keep):
        if i > 0 and _is_tool_related(messages[i]):
            add(i - 1)

    # Fill remaining budget from newest messages first, without splitting a
    # message or changing its contents.
    for i in range(len(messages) - 1, -1, -1):
        if i in keep:
            continue
        candidate_chars = keep_chars + _message_char_count(messages[i])
        if candidate_chars <= max_chars:
            add(i)

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
    return sum(_message_char_count(message) for message in messages)
