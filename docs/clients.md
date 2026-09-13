# Client integration

## OpenAI-compatible clients

The primary compatibility surface is:

```text
Base URL: http://127.0.0.1:8081/v1
Protocol: OpenAI-compatible Chat Completions
```

Use a configured bridge key when `api_keys` is non-empty.

## Hermes

Hermes can point its OpenAI-compatible provider at the bridge. The bridge supplies model responses and tool calls; Hermes remains responsible for local execution.

Recommended smoke sequence:

1. `GET /v1/models`.
2. Ask Hermes to list files in a disposable workspace.
3. Read one known file.
4. Create or edit a known fixture.
5. Run a harmless command.
6. Run `git status`/`git diff` in a disposable repository.
7. Exercise a multi-step task.
8. Repeat with a fresh Hermes session.

The repository's Phase 8 harness and local evidence cover a deterministic compatibility contract, but a new live Gemini Web transport must be revalidated with the real installed Hermes version before release.

## OpenCode

Use the same OpenAI-compatible base URL and authentication model. OpenCode owns its filesystem and terminal tools; the bridge never receives ownership of those operations.

The Phase 8 real-client evidence recorded 13/13 Hermes and 13/13 OpenCode cases. That evidence remains valid as historical client-compatibility evidence, but it does not by itself prove that the current unreleased transport branch can reach Gemini Web today.

## OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8081/v1",
    api_key="local-key",
)

result = client.chat.completions.create(
    model="gemini-3.6-flash",
    messages=[{"role": "user", "content": "Hello"}],
)
```

## curl

Non-streaming:

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_BRIDGE_KEY' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8081/v1/chat/completions \
  -d '{"model":"gemini-3.6-flash","messages":[{"role":"user","content":"Reply with exactly: OK"}],"stream":false}'
```

Streaming:

```bash
curl -N -sS \
  -H 'Authorization: Bearer YOUR_BRIDGE_KEY' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8081/v1/chat/completions \
  -d '{"model":"gemini-3.6-flash","messages":[{"role":"user","content":"Reply with exactly: STREAM_OK"}],"stream":true}'
```

Never replace `YOUR_BRIDGE_KEY` with a real key in documentation or paste the resulting secret-bearing command into an issue.

## Gemini CLI

The repository retains Google-compatible endpoint adapters for Gemini CLI compatibility. These are compatibility surfaces, not evidence that the current Gemini Web upstream transport is identical to Google's public Gemini API.

## Client contract

Clients should assume:

- model names are aliases exposed by the bridge;
- upstream rate/session failures can occur;
- tool calls are proposals returned to the client, not bridge-side execution;
- streaming can surface upstream failures after a stream has begun until the active repair work improves error propagation;
- `/v1/models` is a protocol-layer health check, not an upstream-generation health check.
