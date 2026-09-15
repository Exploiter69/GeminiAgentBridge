# Client integration

## OpenAI-compatible clients

Primary compatibility surfaces:

```text
Base URL: http://127.0.0.1:8081/v1
Protocols: Chat Completions + Responses
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

The repository's Phase 8 harness and historical evidence cover a deterministic compatibility contract, but a changed Gemini Web transport must be revalidated with the real installed Hermes version before release.

## OpenCode

Use the same OpenAI-compatible base URL and authentication model. OpenCode owns its filesystem and terminal tools; the bridge never receives ownership of those operations.

The historical Phase 8 evidence recorded 13/13 Hermes and 13/13 OpenCode cases. That evidence remains useful as regression evidence, but it does not prove that the current unreleased transport branch can reach Gemini Web today.

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

The repository retains Google-compatible endpoint adapters for Gemini CLI compatibility. These are compatibility surfaces, not evidence that the Gemini Web upstream transport is identical to Google's public Gemini API.

## Model contract

The bridge exposes compatibility IDs such as `gemini-3.6-flash`, but the modern backend resolves the requested name against the authenticated Gemini Web account. A compatibility ID must not be interpreted as proof that a particular upstream model is available to every account. Unknown or unavailable models are rejected by the backend resolver rather than silently mapped to an unrelated model.

## Client contract

Clients should assume:

- model availability depends on the authenticated Gemini Web account;
- upstream rate/session failures can occur;
- tool calls are proposals returned to the client, not bridge-side execution;
- streaming commits HTTP success only after the first meaningful upstream delta;
- after stream commitment, upstream failures are emitted as an explicit SSE error event and do not receive a false `[DONE]` success marker;
- `/v1/models` is a protocol-layer catalog and does not by itself prove upstream generation health.
