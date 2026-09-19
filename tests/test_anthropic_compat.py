from gemini_web2api.anthropic_compat import (
    anthropic_messages_to_openai,
    anthropic_response,
    anthropic_tool_choice_to_openai,
    anthropic_tools_to_openai,
)


def test_anthropic_text_request_conversion():
    messages, tools, choice = anthropic_messages_to_openai({
        "system": "You are a coding assistant.",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert messages == [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": "Hello"},
    ]
    assert tools == []
    assert choice == "auto"


def test_anthropic_tools_convert_to_openai_shape():
    tools = anthropic_tools_to_openai([{
        "name": "write_file",
        "description": "Write a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }])
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "write_file"
    assert tools[0]["function"]["parameters"]["required"] == ["path"]


def test_anthropic_tool_use_round_trip_shape():
    messages, tools, choice = anthropic_messages_to_openai({
        "messages": [
            {"role": "user", "content": "Create the file."},
            {"role": "assistant", "content": [{
                "type": "tool_use",
                "id": "toolu_1",
                "name": "write_file",
                "input": {"path": "proof.txt", "content": "OK"},
            }]},
            {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "written",
            }]},
        ],
        "tools": [{"name": "write_file", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "tool", "name": "write_file"},
    })
    assert messages[1]["tool_calls"][0]["id"] == "toolu_1"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "toolu_1"
    assert tools[0]["function"]["name"] == "write_file"
    assert choice == {"function": {"name": "write_file"}}


def test_anthropic_response_maps_tool_use():
    payload = anthropic_response(
        request_model="claude-sonnet-4-6",
        text="",
        tool_calls=[{
            "id": "call_1",
            "function": {"name": "write_file", "arguments": '{"path":"proof.txt"}'},
        }],
        message_id="msg_test",
    )
    assert payload["type"] == "message"
    assert payload["stop_reason"] == "tool_use"
    assert payload["content"][0]["type"] == "tool_use"
    assert payload["content"][0]["input"] == {"path": "proof.txt"}


def test_anthropic_tool_choice_mapping():
    assert anthropic_tool_choice_to_openai("auto") == "auto"
    assert anthropic_tool_choice_to_openai("none") == "none"
    assert anthropic_tool_choice_to_openai("required") == "required"
    assert anthropic_tool_choice_to_openai({"type": "any"}) == "required"
