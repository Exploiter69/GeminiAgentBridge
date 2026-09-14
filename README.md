# GeminiAgentBridge

<p align="center">
  <img src="logo.png" width="200" alt="GeminiAgentBridge logo">
</p>

[中文文档](README_CN.md) · [Documentation](docs/README.md) · [Fixing roadmap](docs/FIXING_ROADMAP.md)

> **Project status:** release-hardening line. The modern Gemini Web transport is the package default, the HTTP boundary is hardened for local/explicitly authenticated remote use, and release promotion is gated on CI plus a fresh authenticated Gemini Web run and real OpenCode/Hermes validation.

**GeminiAgentBridge** provides a local OpenAI-compatible API for using Gemini Web as an agent reasoning backend. Hermes, OpenCode, and similar clients remain responsible for filesystem, terminal, Git, browser, and other downstream tool execution.

## Architecture

```text
Coding Agent
    │
    ▼
OpenAI-compatible GeminiAgentBridge API
    │
    ├── protocol / tool-call normalization
    ├── bounded request + image handling
    └── cancellable streaming
    │
    ▼
gemini-webapi 2.1.1
    │
    ▼
Authenticated Gemini Web session
```

**Hard boundary:** the bridge never executes downstream tools. It returns tool calls; the agent executes them and sends the observation back.

## Release-line guarantees

- Modern `gemini-webapi==2.1.1` transport is the default.
- Modern model names are resolved against the authenticated account at runtime; the compatibility aliases in this repository are not guarantees that a particular model exists on every account.
- Default listener is `127.0.0.1`; non-loopback binding requires configured API keys.
- Request bodies and remote image downloads are bounded.
- Remote image URLs are restricted to public HTTP(S) targets and redirects are revalidated.
- Signed/upload URLs and upstream exception details are not exposed in logs or client errors.
- Gemini Web calls are serialized initially around one long-lived `GeminiClient`; shutdown closes the client before stopping its asyncio loop.
- OpenAI-compatible token `usage` fields are omitted because this bridge does not receive authoritative provider token accounting. It never presents character-count estimates as provider usage.
- Streaming preflights the first upstream delta before committing HTTP 200. If the upstream fails after commitment, the bridge emits a structured `error` SSE event and deliberately does **not** emit `[DONE]` as a success marker.
- A stream is never retried after output has crossed the backend boundary, preventing duplicated tool-call prefixes.
- The old `gemini-web2api` command/module name remains only as a compatibility identity; the maintained implementation is the `gemini_web2api` package.

## Quick start

```bash
git clone https://github.com/Exploiter69/GeminiAgentBridge.git
cd GeminiAgentBridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
# edit config.json and set cookie_file to your local Gemini session file
python -m gemini_web2api --config config.json
```

Python **3.11+** is required by the maintained Gemini Web client. The bridge does not accept or store credentials for you; keep the local session file at restrictive permissions such as `chmod 600`.

Installed entry points:

```bash
gemini-agent-bridge
# compatibility alias:
gemini-web2api
```

Default API base URL:

```text
http://127.0.0.1:8081/v1
```

## Bridge authentication

Loopback use may run without a bridge API key because the service is intentionally local-only by default. **Any non-loopback listener requires at least one `api_keys` entry.** Never expose an unauthenticated instance to a LAN, VPS, container network, or public interface.

Example remote configuration:

```json
{
  "host": "0.0.0.0",
  "api_keys": ["replace-with-a-long-random-key"],
  "cookie_file": "/path/to/gemini-auth.json"
}
```

Clients can authenticate with `Authorization: Bearer <key>`, `x-api-key`, or `x-goog-api-key`.

## Gemini Web session

The modern backend uses a local Gemini Web authentication file. A browser/session-sync helper is included in `gemini-cookie-sync-extension/`, but session material must remain local.

```bash
python -m gemini_web2api --config config.json --cookie-file /path/to/gemini-auth.json
```

Never print, paste, commit, or share session material.

## OpenAI-compatible usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8081/v1",
    api_key="local-bridge-key",
)

response = client.chat.completions.create(
    model="<account-visible-model>",
    messages=[{"role": "user", "content": "Explain recursion simply."}],
)
print(response.choices[0].message.content)
```

Use `GET /v1/models` to discover the models currently visible to the authenticated Gemini Web account. The compatibility aliases remain available for clients that need stable identifiers, but they are resolved by the selected backend and must not be treated as universal upstream model names.

The same base URL is intended for OpenAI-compatible coding agents. See [`docs/clients.md`](docs/clients.md) and the real-client harness at `scripts/phase8_client_compat.py`.

## Tool calling

```text
Gemini → proposes tool call
Bridge → parses / validates / normalizes the protocol
Agent → executes the tool
Agent → returns observation
Bridge → preserves the observation
Gemini → chooses the next action
```

Bridge never executes shell, filesystem, Git, or arbitrary downstream actions.

## Streaming semantics

Chat Completions and Gemini `streamGenerateContent` use SSE. The bridge waits for the first meaningful upstream delta before committing the HTTP success response. If the upstream fails after commitment, the bridge emits a structured `event: error` SSE event and deliberately does **not** emit `[DONE]` as a success marker.

The Responses endpoint uses Responses-style lifecycle events and does not invent token usage. Its current compatibility implementation is buffered upstream: errors occur before the response stream is committed, while chat streaming uses the true upstream iterator.

Client disconnects close the downstream iterator so the modern backend can cancel the upstream asyncio task rather than continuing generation after the agent has gone away.

## Legacy boundary

The original direct `StreamGenerate` transport remains available only when `upstream_backend=legacy` is selected explicitly. `upstream_backend=auto` falls back to legacy only when the maintained modern package is unavailable; ordinary modern authentication, model, protocol, or upstream failures are not silently rerouted to a different transport. Legacy-only numeric `@think=N` semantics are not fabricated by the modern backend.

## Docker

Do not bake cookies or API keys into an image. Mount them at runtime:

```bash
docker build -t gemini-agent-bridge .
docker run --rm -p 8081:8081 \
  -v "$PWD/config.json:/app/config.json:ro" \
  -v "$PWD/cookies.json:/app/cookies.json:ro" \
  gemini-agent-bridge
```

For a container reachable through the published port, the mounted config must explicitly use a non-loopback bind such as `0.0.0.0` **and** include an API key. The startup guard refuses an unauthenticated remote bind.

## Verification

Deterministic CI covers Python 3.11–3.14. Local verification:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall gemini_web2api scripts tests
git diff --check
```

Authenticated live transport smoke test (credentials stay on your machine):

```bash
python scripts/live_gemini_web_test.py --cookie-file /path/to/gemini-auth.json --stream
```

Real-client validation:

```bash
python scripts/phase8_client_compat.py --opencode --live --cookie-file /path/to/gemini-auth.json --model <account-visible-model>
python scripts/phase8_client_compat.py --hermes --live --cookie-file /path/to/gemini-auth.json --model <account-visible-model>
```

Those commands require the corresponding client to already be installed. They use disposable workspaces and never print the cookie file.

## Troubleshooting

| Symptom | Likely layer |
|---|---|
| `/v1/models` works but generation is unauthenticated | Gemini Web session/authentication |
| `401` on a remote listener | bridge API key |
| `413` | request body limit |
| image URL rejected | SSRF/public-address policy |
| stream ends with an error event and no `[DONE]` | upstream failed after stream commitment |
| HTTP 405 mentioning `StreamGenerate` | an explicitly selected legacy transport |
| model rejected as unavailable | model is not visible to the authenticated Gemini Web account |
| port already in use | another local server process |

When reporting failures, provide status codes, exception **types**, timestamps, and command shape. Never provide cookies, API keys, authorization headers, or session files.

## License

MIT. See [`LICENSE`](LICENSE).
