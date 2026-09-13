"""gemini-web2api: Gemini Web to OpenAI API proxy."""
__version__ = "1.1.0"

from . import tools as _tools
from . import gemini as _gemini
from .protocol import (
    STRICT_TOOL_PROTOCOL,
    build_repair_prompt,
    get_tool_context,
    parse_tool_calls_robust,
    response_needs_repair,
    set_tool_context,
    validate_tool_calls,
)

_original_messages_to_prompt = _tools.messages_to_prompt
_original_generate = _gemini.generate


def _messages_to_prompt_with_protocol(
    messages,
    tools=None,
    tool_choice=None,
    grounding=None,
    max_chars=None,
):
    prompt, images = _original_messages_to_prompt(
        messages,
        tools,
        tool_choice,
        grounding=grounding,
        max_chars=max_chars,
    )
    set_tool_context(tools or [], tool_choice or "auto")
    if tools and tool_choice != "none":
        prompt = f"{prompt}\n\n{STRICT_TOOL_PROTOCOL}"
    return prompt, images


def _generate_with_repair(prompt, model_id, think_mode=False, file_refs=None, extra_fields=None):
    text = _original_generate(prompt, model_id, think_mode, file_refs, extra_fields)
    tool_defs, tool_choice = get_tool_context()
    if not tool_defs or tool_choice == "none":
        return text

    for _ in range(2):
        clean, calls = parse_tool_calls_robust(text or "")
        errors = validate_tool_calls(calls, tool_defs)
        if not response_needs_repair(text or "", calls, tool_defs, tool_choice):
            return text
        repaired_prompt = build_repair_prompt(prompt, errors)
        text = _original_generate(repaired_prompt, model_id, think_mode, file_refs, extra_fields)
    return text


# Keep the existing public API stable while upgrading the parser and prompt.
_tools.messages_to_prompt = _messages_to_prompt_with_protocol
_tools.parse_tool_calls = parse_tool_calls_robust
_gemini.generate = _generate_with_repair
