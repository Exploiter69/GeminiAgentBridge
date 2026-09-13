"""GeminiAgentBridge: Gemini Web reasoning bridge with an OpenAI-compatible API."""
__version__ = "2.0.0"

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