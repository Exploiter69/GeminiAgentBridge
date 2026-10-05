# Claude Code Compatibility

GeminiAgentBridge exposes an Anthropic-compatible Messages API at `/v1/messages`.
The bridge does not execute client tools: Claude Code owns the tool loop and sends
tool results back on the next Messages request.

## Supported agent loop

The intended trajectory is:

1. Claude Code sends a user/system turn plus its custom tools.
2. GeminiAgentBridge converts the Anthropic request to the internal tool protocol.
3. Gemini Web produces a tool call.
4. The bridge returns an Anthropic `tool_use` content block.
5. Claude Code executes the tool locally.
6. Claude Code sends the `tool_result` content block in the next request.
7. The bridge preserves that result and the loop continues.

## Local configuration

Start the bridge with an authenticated Gemini Web session and the modern backend.
Then point Claude Code at the bridge instead of the Anthropic service:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8081"
export ANTHROPIC_API_KEY="${BRIDGE_API_KEY:-local}"
export ANTHROPIC_MODEL="claude-sonnet-4-6"
claude
```

If the bridge is configured with API keys, use the configured bridge key for
`ANTHROPIC_API_KEY`. Do not put Gemini session cookies into Claude Code
configuration.

## Direct protocol smoke test

Before testing Claude Code, verify the Messages endpoint and a named tool choice:

```bash
curl -sS http://127.0.0.1:8081/v1/messages \
  -H "content-type: application/json" \
  -H "x-api-key: ${BRIDGE_API_KEY}" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 200,
    "messages": [{"role": "user", "content": "Read sample.txt"}],
    "tools": [{
      "name": "read_file",
      "description": "Read a file.",
      "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"]
      }
    }],
    "tool_choice": {"type": "tool", "name": "read_file"}
  }'
```

A successful tool-use response contains an Anthropic `tool_use` block. The
bridge must not silently turn an invalid tool choice into `auto`.

## Important limitations

- Anthropic server-side tools are not fabricated or silently dropped. If a
  client sends an unsupported server-side tool type, the bridge returns an
  explicit request error.
- The bridge does not execute Claude Code's tools. Tool execution remains the
  client's responsibility.
- Gemini Web authentication and model availability still determine whether the
  upstream generation succeeds.
- A real Claude Code multi-turn coding task is the final acceptance test; unit
  tests alone do not prove agentic compatibility.
