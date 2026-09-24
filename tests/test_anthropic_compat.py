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
    assert anthropic_tool_choice_to_openai({"type": "required"}) == "required"
    assert anthropic_tool_choice_to_openai({"type": "auto"}) == "auto"
    assert anthropic_tool_choice_to_openai({"type": "none"}) == "none"



def test_hardened_handler_dispatches_anthropic_messages():
    from gemini_web2api.hardened_server import HardenedGeminiHandler

    handler = HardenedGeminiHandler.__new__(HardenedGeminiHandler)
    handler.path = "/v1/messages"
    handler._authorized = lambda: True
    handler._read_request_body = lambda: b'{"messages":[{"role":"user","content":"hello"}]}'
    calls = []
    handler._handle_anthropic_messages = lambda body: calls.append(body)

    HardenedGeminiHandler.do_POST(handler)

    assert calls == [b'{"messages":[{"role":"user","content":"hello"}]}']

def test_production_anthropic_tool_choice_survives_phase4_runtime():
    """Exercise the same base+Hardened installation used by __main__."""
    from gemini_web2api import server
    from gemini_web2api.hardened_server import HardenedGeminiHandler
    from gemini_web2api.phase4_runtime import install_phase4_runtime

    class DummyWFile:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        def flush(self):
            pass

    class_attrs = {}
    for cls in (server.GeminiHandler, HardenedGeminiHandler):
        class_attrs[cls] = {
            name: getattr(cls, name, None)
            for name in (
                "send_json",
                "_handle_anthropic_messages",
                "do_POST",
                "_phase4_installed",
            )
        }

    module_attrs = {
        name: getattr(server, name, None)
        for name in (
            "messages_to_prompt",
            "parse_tool_calls",
            "generate",
            "_phase5_generate_wrapped",
            "_phase5_stream_wrapped",
            "_phase5_legacy_generate_wrapped",
        )
    }
    original_upload_images = server._upload_images
    original_generate = server.generate

    try:
        def fake_generate(*_args, **_kwargs):
            return (
                "@@TOOL_CALL@@\n"
                '{"name":"calculator","arguments":{"a":7,"b":6}}\n'
                "@@END_TOOL_CALL@@"
            )

        server.generate = fake_generate
        server._upload_images = lambda _images: None

        # This mirrors __main__.py exactly.
        install_phase4_runtime(server.GeminiHandler)
        install_phase4_runtime(HardenedGeminiHandler)

        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": "Calculate 7 multiplied by 6."}],
            "tools": [{
                "name": "calculator",
                "description": "Calculate a multiplication.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            }],
            "tool_choice": {"type": "tool", "name": "calculator"},
        }).encode()

        handler = HardenedGeminiHandler.__new__(HardenedGeminiHandler)
        handler.wfile = DummyWFile()
        handler.send_json = lambda data, status=200: setattr(handler, "_captured", (status, data))

        HardenedGeminiHandler._handle_anthropic_messages(handler, body)

        status, payload = handler._captured
        assert status == 200
        assert payload["stop_reason"] == "tool_use"
        assert payload["content"][0]["type"] == "tool_use"
        assert payload["content"][0]["name"] == "calculator"
        assert payload["content"][0]["input"] == {"a": 7, "b": 6}
    finally:
        server._upload_images = original_upload_images
        server.generate = original_generate

        for name, value in module_attrs.items():
            if value is None:
                try:
                    delattr(server, name)
                except AttributeError:
                    pass
            else:
                setattr(server, name, value)

        for cls, attrs in class_attrs.items():
            for name, value in attrs.items():
                if value is None:
                    try:
                        delattr(cls, name)
                    except AttributeError:
                        pass
                else:
                    setattr(cls, name, value)
