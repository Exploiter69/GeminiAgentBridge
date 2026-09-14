"""Tool calling and multimodal message parsing."""
import json
import re
import uuid
import base64
import binascii
import io
from urllib.parse import unquote_to_bytes

from .config import CONFIG
from .context import compact_messages
from .grounding import GroundingFacts
from .tool_schema import normalize_tool_definitions
from .protocol import parse_tool_calls_robust, set_tool_context, get_tool_context, validate_tool_calls, validate_tool_choice, clear_tool_context

MAX_IMAGE_B64_SIZE = 50000


def _compress_b64_if_needed(b64: str) -> str:
    if len(b64) <= MAX_IMAGE_B64_SIZE:
        return b64
    try:
        from PIL import Image
        img_data = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_data))
        max_dim = 256
        ratio = min(max_dim / img.width, max_dim / img.height)
        if ratio < 1:
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64[:MAX_IMAGE_B64_SIZE]


def _build_tool_choice_instruction(tool_choice, tool_defs: list) -> str:
    if tool_choice == "none":
        return "\n\nIMPORTANT: Do NOT call any tools. Respond with text only."
    if tool_choice == "required":
        return "\n\nIMPORTANT: You MUST call at least one tool. Do not respond with text only."
    if isinstance(tool_choice, dict):
        fn_name = tool_choice.get("function", {}).get("name", "")
        if fn_name:
            return f'\n\nIMPORTANT: You MUST call the tool "{fn_name}". Do not call other tools.'
    return ""


def _decode_data_url(url: str):
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", url, re.DOTALL)
    if not match:
        return None
    mime = match.group(1) or "image/png"
    is_base64 = bool(match.group(2))
    data = match.group(3)
    try:
        if is_base64:
            return base64.b64decode(data, validate=True), mime
        return unquote_to_bytes(data), mime
    except (ValueError, TypeError, binascii.Error):
        return None


def _image_from_url(url: str, mime: str = None):
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        return _decode_data_url(url)
    return url, mime or "image/png"


def _image_from_part(part: dict):
    part_type = part.get("type")
    if part_type == "image_url":
        image_url = part.get("image_url", {})
        if isinstance(image_url, dict):
            return _image_from_url(image_url.get("url"), image_url.get("mime_type"))
        return _image_from_url(image_url)
    if part_type in ("input_image", "image"):
        image_url = part.get("image_url") or part.get("url")
        if isinstance(image_url, dict):
            return _image_from_url(image_url.get("url"), image_url.get("mime_type"))
        if image_url:
            return _image_from_url(image_url, part.get("mime_type"))
        image_data = part.get("data") or part.get("base64")
        if isinstance(image_data, str):
            mime = part.get("mime_type") or part.get("media_type") or "image/png"
            if image_data.startswith("data:"):
                return _decode_data_url(image_data)
            try:
                return base64.b64decode(image_data, validate=True), mime
            except (ValueError, TypeError, binascii.Error):
                return None
    return None


def messages_to_prompt(messages: list, tools: list = None, tool_choice=None, grounding: GroundingFacts | None = None, max_chars: int | None = None) -> tuple:
    tool_defs = normalize_tool_definitions(tools or []) if tools else []
    set_tool_context(tool_defs, tool_choice if tool_choice is not None else "auto")
    budget = max_chars if max_chars is not None else int(CONFIG.get("prompt_soft_budget_chars", 0))
    if budget > 0:
        messages, _ = compact_messages(messages, budget)

    parts = []
    images = []
    if grounding and grounding.is_explicit:
        parts.append(grounding.to_prompt())

    if tool_defs and tool_choice != "none":
        constraint = _build_tool_choice_instruction(tool_choice, tool_defs)
        tool_json = json.dumps(tool_defs, ensure_ascii=False, separators=(",", ":"))
        parts.append(
            "# Tool Use\n\n"
            "You can call the following tools. Call format:\n"
            '```tool_call\n{"name": "func_name", "arguments": {...}}\n```\n'
            "When calling tools, output ONLY the tool_call block(s).\n\n"
            f"Available tools:\n{tool_json}{constraint}"
        )

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") in ("text", "input_text"):
                    text_parts.append(c.get("text", ""))
                else:
                    image = _image_from_part(c)
                    if image:
                        images.append(image)
                        text_parts.append("[Image attached]")
            content = " ".join(text_parts)
        if role == "system":
            parts.append(f"[System instruction]: {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                tc_strs = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tc_strs.append(f'```tool_call\n{{"name": "{fn.get("name")}", "arguments": {fn.get("arguments", "{}")}}}\n```')
                parts.append(f"[Assistant]: {content or ''}\n" + "\n".join(tc_strs))
            else:
                parts.append(f"[Assistant]: {content}")
        elif role == "tool":
            parts.append(f"[Tool result for {msg.get('name', '')}]: {content}")
        else:
            parts.append(content if content else "")

    return "\n\n".join(p for p in parts if p), images


def parse_tool_calls(text: str) -> tuple:
    clean, calls = parse_tool_calls_robust(text)
    tool_defs, tool_choice = get_tool_context()
    errors = validate_tool_choice(tool_choice, tool_defs)
    errors.extend(validate_tool_calls(calls, tool_defs))
    if tool_choice == "none" and calls:
        errors.append("tool_choice=none forbids tool calls")
    if tool_choice == "required" and not calls:
        errors.append("tool_choice=required requires at least one tool call")
    if errors:
        clear_tool_context()
        raise ValueError("invalid tool call protocol: " + "; ".join(errors[:8]))
    clear_tool_context()
    return clean, calls


def build_tool_prompt(tool_defs: list) -> str:
    compact_defs = normalize_tool_definitions(tool_defs)
    tool_spec = json.dumps(compact_defs, ensure_ascii=False, separators=(",", ":"))
    return (
        "# Tool Use\n\n"
        "You can call the following tools to help accomplish tasks. These tools connect to the user's local environment and will execute when called.\n\n"
        "Call format (use this exact format):\n"
        "```function_call\n"
        '{"name": "<tool_name>", "args": {<arguments>}}\n'
        "```\n\n"
        "When calling tools:\n"
        "- Output ONLY the function_call block(s), nothing else\n"
        "- You may call multiple tools with multiple blocks\n"
        "- After receiving a [Tool result for ...], use that data to answer the user\n\n"
        f"Available tools:\n{tool_spec}"
    )


def _google_tool_choice_instruction(req: dict) -> str:
    tool_config = req.get("toolConfig", {})
    fc_config = tool_config.get("functionCallingConfig", {})
    mode = fc_config.get("mode", "AUTO")
    allowed = fc_config.get("allowedFunctionNames", [])
    if mode == "NONE":
        return "\n\nIMPORTANT: Do NOT call any tools. Respond with text only."
    if mode == "ANY":
        if allowed:
            names = ", ".join(f'"{n}"' for n in allowed)
            return f"\n\nIMPORTANT: You MUST call one of these tools: {names}. Do not respond with text only."
        return "\n\nIMPORTANT: You MUST call at least one tool. Do not respond with text only."
    return ""


def google_contents_to_prompt(req: dict) -> tuple:
    parts = []
    images = []
    tool_config = req.get("toolConfig", {})
    fc_mode = tool_config.get("functionCallingConfig", {}).get("mode", "AUTO")
    tools = req.get("tools")
    tool_defs = []
    if tools and fc_mode != "NONE":
        for tool_group in tools:
            for fn in tool_group.get("functionDeclarations", []):
                td = {"name": fn.get("name", ""), "description": fn.get("description", "")}
                params = fn.get("parameters") or fn.get("parametersJsonSchema")
                if params:
                    td["parameters"] = params
                tool_defs.append(td)
    sys_inst = req.get("systemInstruction")
    if sys_inst:
        sys_text = " ".join(p.get("text", "") for p in sys_inst.get("parts", []) if p.get("text"))
        if sys_text:
            parts.append(sys_text + ("\n\n" + build_tool_prompt(tool_defs) + _google_tool_choice_instruction(req) if tool_defs else ""))
    elif tool_defs:
        parts.append(build_tool_prompt(tool_defs) + _google_tool_choice_instruction(req))

    for content in req.get("contents", []):
        role = content.get("role", "user")
        msg_parts = []
        for p in content.get("parts", []):
            if p.get("text"):
                msg_parts.append(p["text"])
            elif p.get("inlineData"):
                data = p["inlineData"]
                try:
                    images.append((base64.b64decode(data["data"], validate=True), data.get("mimeType", "image/png")))
                    msg_parts.append("[Image attached]")
                except (KeyError, ValueError, TypeError, binascii.Error):
                    pass
            elif p.get("functionCall"):
                fc = p["functionCall"]
                msg_parts.append(f'```function_call\n{json.dumps({"name": fc["name"], "args": fc.get("args", {})}, ensure_ascii=False)}\n```')
            elif p.get("functionResponse"):
                fr = p["functionResponse"]
                msg_parts.append(f'[Tool result for {fr.get("name", "")}]: {json.dumps(fr.get("response", {}), ensure_ascii=False)}')
        text = "\n".join(msg_parts)
        parts.append(f"[Assistant]: {text}" if role == "model" else text)
    return "\n\n".join(p for p in parts if p), images


def parse_google_function_calls(text: str) -> tuple:
    function_calls = []
    patterns = [r'```function_call\s*\n(.*?)\n```', r'(?:^|\n)function_call\s*\n(\{.*?\})']
    clean = text
    for pattern in patterns:
        for match in re.findall(pattern, clean, re.DOTALL):
            try:
                data = json.loads(match.strip())
                if "name" in data:
                    function_calls.append({"name": data["name"], "args": data.get("args", data.get("arguments", {}))})
            except (json.JSONDecodeError, KeyError):
                pass
        clean = re.sub(pattern, "", clean, flags=re.DOTALL).strip()
    if not function_calls and clean.strip().startswith("{"):
        try:
            data = json.loads(clean.strip())
            if "name" in data and ("args" in data or "arguments" in data):
                function_calls.append({"name": data["name"], "args": data.get("args", data.get("arguments", {}))})
                clean = ""
        except (json.JSONDecodeError, KeyError):
            pass
    return clean, function_calls
