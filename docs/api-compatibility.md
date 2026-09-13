# API compatibility

## Primary HTTP surface

### `GET /v1/models`

Returns the bridge's client-facing model catalog.

Use this to verify that the HTTP server is alive and that bridge authentication is configured correctly. It does **not** prove that Gemini Web generation is authenticated or available.

### `POST /v1/chat/completions`

OpenAI-style chat generation with optional streaming and tool definitions.

Typical request:

```json
{
  "model": "gemini-3.6-flash",
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "stream": false
}
```

Tool definitions use the OpenAI function-tool shape. The bridge validates and normalizes model-generated tool calls before returning them.

### `POST /v1/responses`

The repository contains a Responses compatibility layer used by the project's Codex-oriented contract tests. The exact supported fields should be verified against the current tests rather than assuming full parity with OpenAI's evolving Responses API.

## Google-compatible compatibility surface

The package also contains adapters for Google-style model endpoints used by Gemini CLI compatibility tests, including model listing and generate/stream-generate routes.

These routes are a compatibility layer. They do not turn Gemini Web into the official Gemini API and should not be documented as an official Google endpoint.

## Authentication

If `api_keys` is non-empty, requests require a matching bridge credential. Authentication is local to this service.

Gemini Web session authentication is separate and happens after request validation.

## Error model

The bridge reports protocol and upstream failures as structured JSON where the response has not already entered an SSE stream.

Typical classes include:

- authentication/session failure;
- upstream timeout;
- upstream rate/throttle response;
- malformed model output;
- invalid tool arguments;
- unavailable modern transport dependency;
- empty upstream response.

A request that has already emitted SSE data cannot be converted back into a normal HTTP JSON error. The current repair work tracks this as an error-propagation limitation.

## Tool-call contract

The bridge may:

- normalize `args` and `arguments`;
- parse JSON strings where the protocol explicitly permits them;
- deduplicate identical calls within a model response;
- validate JSON Schema;
- perform bounded deterministic repair;
- return a failed/invalid result to the client when repair cannot safely succeed.

The bridge may not:

- invent a tool name;
- invent a filesystem path;
- invent a tool result;
- execute a shell command;
- mutate the client's workspace.

## Compatibility philosophy

The project targets the subset of OpenAI-style behavior needed by real agent clients rather than claiming perfect feature parity. Every newly claimed compatibility behavior should have a deterministic regression test and, for client-specific claims, a real-client gate where practical.
