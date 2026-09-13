# GeminiAgentBridge

<p align="center">
  <img src="logo.png" width="200" alt="GeminiAgentBridge logo">
</p>

[中文文档](README_CN.md) · [Documentation](docs/README.md) · [Roadmap](roadmap.md)

> **Project status:** active transport-repair cycle. This repository is an independently maintained GeminiAgentBridge project; the current branch contains the modern Gemini Web transport work and is not yet a released production baseline. See `docs/release-status.md`.

**GeminiAgentBridge** provides a local OpenAI-compatible API for using Gemini Web as an agent reasoning backend. Hermes, OpenCode, and similar clients remain responsible for filesystem, terminal, Git, and other downstream tool execution.

## Identity

This repository is branded and maintained as **GeminiAgentBridge**. The internal `gemini_web2api` Python module and the `gemini-web2api` compatibility command remain intentionally stable so existing local integrations do not break.

## Architecture

```text
Gemini Web
   │
   │ current maintained web transport
   ▼
┌──────────────────────────────┐
│ GeminiAgentBridge            │
│                              │
│ OpenAI-compatible HTTP API   │
│ prompt/context construction  │
│ tool-call parsing/validation │
│ bounded repair/recovery      │
│ grounding + observability    │
└──────────────┬───────────────┘
               │
               ▼
       Hermes / OpenCode
               │
       filesystem / shell / Git
```

**Hard boundary:** the bridge does not execute downstream tools. It can parse, validate, repair, classify, and return tool calls; Hermes/OpenCode executes them and returns observations.

## What is current

- OpenAI-compatible Chat Completions and model listing.
- Responses/API compatibility layers used by the project test suite.
- Function/tool-call parsing, schema validation, bounded repair, and recovery.
- Explicit grounding/context handling and observation-integrity rules.
- Structured credential-redacted request lifecycle telemetry.
- Conservative enum coercion and bounded retry/stability logic.
- Hermes/OpenCode compatibility harnesses and trajectory regression benchmarks.
- Modern Gemini Web transport through `gemini-webapi==2.1.1` on the repair branch.
- The old direct `StreamGenerate` transport remains available only as an explicit legacy compatibility backend.

## Important transport status

The modern transport is the default in the package entrypoint and configuration defaults. It uses a long-lived `GeminiClient`, a persistent background asyncio loop, and a local cookie/auth file when authenticated Gemini Web access is required.

The current repair work was triggered because the older direct Gemini `StreamGenerate` route produced HTTP 405 responses against current Gemini Web behavior. Do not interpret an old 405 from a process started with the historical `python gemini_web2api.py` entrypoint as proof that the repaired package transport is using the same route.

A live authenticated Gemini Web session is still required to prove end-to-end upstream generation. If the session is expired, the maintained client reports an authentication failure; that is distinct from a bridge protocol failure.

## Quick start

```bash
git clone https://github.com/Exploiter69/GeminiAgentBridge.git
cd GeminiAgentBridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python -m gemini_web2api
```

Python **3.11+** is required by the maintained Gemini Web client.

The compatibility command is also available after installation:

```bash
gemini-agent-bridge
# compatibility alias:
gemini-web2api
```

Default API base URL:

```text
http://127.0.0.1:8081/v1
```

## Gemini Web session

The modern transport can consume a local Gemini authentication file. The repository includes `gemini-cookie-sync-extension/` for exporting the browser session locally.

```bash
python -m gemini_web2api --cookie-file /path/to/gemini-auth.json
```

Never print, paste, commit, or share session material. Use restrictive permissions such as `chmod 600`.

## OpenAI-compatible usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8081/v1",
    api_key="local-bridge-key",
)

response = client.chat.completions.create(
    model="gemini-3.1-pro",
    messages=[{"role": "user", "content": "Explain recursion simply."}],
)

print(response.choices[0].message.content)
```

The same base URL can be used by OpenAI-compatible agent clients such as Hermes/OpenCode. See [`docs/clients.md`](docs/clients.md).

## Configuration

See [`docs/configuration.md`](docs/configuration.md). Important fields include `upstream_backend`, `cookie_file`, `proxy`, `api_keys`, `temporary_chats`, retry limits, and prompt/tool budgets.

## Tool calling

```text
Gemini → proposes tool call
Bridge → validates / normalizes / bounded-repairs
Hermes/OpenCode → executes tool
Hermes/OpenCode → returns observation
Bridge → preserves observation integrity
Gemini → chooses next action
```

Bridge never executes Shell, filesystem, Git, or arbitrary downstream actions itself.

## Streaming

Chat Completions streaming uses SSE. The package uses the modern upstream transport and true downstream streaming where supported.

A known repair item is upstream failure after an initial SSE header/chunk has been emitted. A partial stream must never be interpreted as a successful completed generation.

## Authentication layers

There are two independent authentication layers:

1. **Bridge authentication:** optional local `api_keys`.
2. **Gemini Web authentication:** the local session/cookie file used by the upstream client.

A successful `/v1/models` request proves only that the bridge HTTP layer is reachable; it does not prove Gemini Web authentication.

## Docker

Docker remains supported. Mount configuration and authentication files read-only where practical; never bake session material into an image.

```bash
docker build -t gemini-agent-bridge .
docker run --rm -p 8081:8081 \
  -v "$PWD/config.json:/app/config.json:ro" \
  gemini-agent-bridge
```

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

| Symptom | Likely layer |
|---|---|
| `/v1/models` works, generation says unauthenticated | Gemini Web session |
| HTTP 405 mentioning `StreamGenerate` | historical legacy process/transport |
| HTTP 429 from current upstream | upstream throttling/anti-abuse/session/network behavior |
| 401/403 before upstream request | bridge authentication |
| port already in use | another server process |
| stream starts then fails | active stream error-propagation limitation |

When reporting failures, provide redacted status codes, error types, timestamps, and command shape. Never provide cookies, API keys, authorization headers, or session files.

## Verification

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall gemini_web2api scripts tests
git diff --check
```

See [`docs/development.md`](docs/development.md) and [`docs/release-status.md`](docs/release-status.md) for the complete verification policy.

## Project history

The repository has completed the protocol, grounding, recovery, tool-choice, planner, real-client compatibility, trajectory, observability, selective feature-port, stability, and release-verification phases. The current transport repair is a separate gate because real-client testing exposed the stale direct `StreamGenerate` path.

Synthetic tests are not treated as proof of live Gemini Web availability, and model output is never treated as proof that a downstream tool executed.

## License

MIT. See [`LICENSE`](LICENSE).
