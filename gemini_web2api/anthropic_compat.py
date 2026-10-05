"""Anthropic Messages API compatibility helpers.

The bridge remains Gemini-backed: this module translates Anthropic wire-format
messages/tool definitions into the bridge's existing OpenAI-shaped internal
representation and formats the result back into Anthropic content blocks.
It does not execute client tools.
"""
from __future__ import annotations

import json
from typing import Any

from .protocol import validate_tool_choice


def _text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_result":
            value = block.get("content", "")
            if isinstance(value, list):
                value = _text_blocks(value)
            parts.append(str(value))
    return "\n".join(p for p in parts if p)


def _anthropic_content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _text_blocks(content)
    result = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            result.append({"type": "text", "text": block.get("text", "")})
        elif kind == "image":
            source = block.get("source") or {}
            if source.get("type") == "base64" and source.get("data"):
                media = source.get("media_type", "image/png")
                result.append({"type": "image_url", "image_url": {
                    "url": f"data:{media};base64,{source['data']}"
                }})
            elif source.get("type") == "url" and source.get("url"):
                result.append({"type": "image_url", "image_url": {
                    "url": source["url"]
                }})
        elif kind == "tool_result":
            # Handled at message level so tool_call_id is preserved.
            continue
    if len(result) == 1 and result[0].get("type") == "text":
        return result[0]["text"]
    return result


def anthropic_tools_to_openai(tools: Any) -> list[dict]:
    result = []
    for index, tool in enumerate(tools or []):
        if not isinstance(tool, dict):
            raise ValueError(f"unsupported Anthropic tool at index {index}")
        tool_type = tool.get("type")
        if tool_type not in (None, "custom"):
            raise ValueError(f"unsupported Anthropic tool type: {tool_type!r}")
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Anthropic tool at index {index} is missing a name")
        result.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return result


def anthropic_tool_choice_to_openai(choice: Any) -> Any:
    if not choice:
        return "auto"
    if isinstance(choice, str):
        if choice in {"auto", "none", "required"}:
            return choice
        raise ValueError(f"unsupported Anthropic tool_choice: {choice!r}")
    if isinstance(choice, dict):
        if choice.get("type") in {"any", "required"}:
            return "required"
        if choice.get("type") == "auto":
            return "auto"
        if choice.get("type") == "none":
            return "none"
        if choice.get("type") == "tool" and choice.get("name"):
            return {"function": {"name": choice["name"]}}
    raise ValueError("unsupported Anthropic tool_choice")


def _validate_anthropic_tool_trajectory(messages: Any) -> None:
    """Validate client-supplied tool blocks before sending them upstream.

    The bridge cannot execute tools, so malformed tool_result blocks must never
    be converted into anonymous tool messages and silently accepted. Likewise,
    a result must reference a tool_use ID that exists in the supplied
    conversation history.
    """
    tool_use_ids: set[str] = set()
    for message_index, message in enumerate(messages or []):
        if not isinstance(message, dict):
            raise ValueError(f"message at index {message_index} must be an object")
        content = message.get("content", "")
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                raise ValueError(
                    f"message content block at index {message_index}:{block_index} must be an object"
                )
            kind = block.get("type")
            if kind == "tool_use":
                tool_id = block.get("id")
                name = block.get("name")
                if not isinstance(tool_id, str) or not tool_id.strip():
                    raise ValueError(
                        f"tool_use at message {message_index} is missing an id"
                    )
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(
                        f"tool_use at message {message_index} is missing a name"
                    )
                if tool_id in tool_use_ids:
                    raise ValueError(f"duplicate tool_use id {tool_id!r}")
                tool_use_ids.add(tool_id)
            elif kind == "tool_result":
                tool_id = block.get("tool_use_id")
                if not isinstance(tool_id, str) or not tool_id.strip():
                    raise ValueError(
                        f"tool_result at message {message_index} is missing tool_use_id"
                    )
                if tool_id not in tool_use_ids:
                    raise ValueError(
                        f"tool_result references unknown tool_use_id {tool_id!r}"
                    )


def anthropic_messages_to_openai(req: dict[str, Any]) -> tuple[list[dict], list[dict], Any]:
    messages = req.get("messages", [])
    _validate_anthropic_tool_trajectory(messages)

    converted_messages = []
    system = req.get("system")
    if system:
        converted_messages.append({"role": "system", "content": _text_blocks(system)})

    for message in messages:
        if not isinstance(message, dict):
            # _validate_anthropic_tool_trajectory has already rejected this.
            continue
        role = message.get("role")
        content = message.get("content", "")
        if role == "assistant":
            text = _anthropic_content_to_openai(content)
            tool_calls = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        })
            item = {"role": "assistant", "content": text if text else None}
            if tool_calls:
                item["tool_calls"] = tool_calls
            converted_messages.append(item)
        elif role == "user" and isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    value = block.get("content", "")
                    if isinstance(value, list):
                        value = _text_blocks(value)
                    converted_messages.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(value),
                    })
                elif block.get("type") in ("text", "image"):
                    converted = _anthropic_content_to_openai([block])
                    if converted:
                        converted_messages.append({"role": "user", "content": converted})
        else:
            converted_messages.append({"role": role or "user", "content": _anthropic_content_to_openai(content)})

    tools = anthropic_tools_to_openai(req.get("tools"))
    choice = anthropic_tool_choice_to_openai(req.get("tool_choice"))
    choice_errors = validate_tool_choice(choice, tools)
    if choice_errors:
        raise ValueError("invalid Anthropic tool_choice: " + "; ".join(choice_errors))
    return converted_messages, tools, choice


def anthropic_response(
    *,
    request_model: str,
    text: str,
    tool_calls: list[dict] | None,
    message_id: str,
) -> dict:
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for call in tool_calls or []:
        fn = call.get("function", {})
        try:
            tool_input = json.loads(fn.get("arguments", "{}"))
        except (TypeError, ValueError):
            tool_input = {}
        content.append({
            "type": "tool_use",
            "id": call.get("id", ""),
            "name": fn.get("name", ""),
            "input": tool_input,
        })
    stop_reason = "tool_use" if tool_calls else "end_turn"
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": request_model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
