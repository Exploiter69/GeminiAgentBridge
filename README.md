# gemini-web2api

<p align="center">
  <img src="logo.png" width="200" alt="gemini-web2api logo">
</p>

[中文文档](README_CN.md) · [Documentation](docs/README.md) · [Roadmap](roadmap.md)

> **Project status:** the repository is in an active transport-repair cycle. The current `repair-live-gemini-web` branch contains the modern Gemini Web transport work, but it is **not a released/merged production baseline yet**. See `docs/release-status.md` for the current release gate.

`gemini-web2api` converts Gemini Web into a local OpenAI-compatible HTTP API so agent clients such as Hermes and OpenCode can use Gemini as their reasoning backend while keeping filesystem, terminal, Git, and other tool execution inside the agent client.

## Architecture

```text
Gemini Web
   │
   │ current maintained web transport
   ▼
┌──────────────────────────────┐
│ gemini-web2api               │
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
- **Modern Gemini Web transport** through `gemini-webapi==2.1.1` on the repair branch.
- The old direct `StreamGenerate` transport remains available only as an explicit legacy compatibility backend.

## Important transport status

The modern transport is the default in the package entrypoint and configuration defaults. It uses a long-lived `GeminiClient`, a persistent background asyncio loop, and a local cookie/auth file when authenticated Gemini Web access is required.

The current repair work was triggered because the older direct Gemini `StreamGenerate` route produced HTTP 405 responses against current Gemini Web behavior. Do **not** interpret an old 405 from a process started with `python gemini_web2api.py` as proof that the repaired package transport is using the same route.

A live authenticated Gemini Web session is still required to prove end-to-end upstream generation. If the session is expired, the maintained client reports an authentication failure; that is distinct from a bridge protocol failure.

## Quick start

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/Exploiter69/GeminiAgentBridge.git
git clone --branch repair-live-gemini-web https://github.com/Exploiter69/GeminiAgentBridge.git gemini-web2api-repair
cd gemini-web2api-repair

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python **3.11+** is required by the maintained Gemini Web client used by the current transport.

### 2. Create configuration

```bash
cp config.example.json config.json
```

Keep `config.json` private; it is ignored by Git.

For the modern authenticated transport, configure a local `cookie_file` containing the required Gemini session material. The repository includes a browser extension under `gemini-cookie-sync-extension/` to export that data locally without sending it to a third party. See [`gemini-cookie-sync-extension/SETUP.md`](gemini-cookie-sync-extension/SETUP.md).

### 3. Start the package server

Preferred entrypoint:

```bash
source .venv/bin/activate
python -m gemini_web2api
```

or:

```bash
gemini-web2api
```

Default API base URL:

```text
http://127.0.0.1:8081/v1
```

Use `--port`, `--config`, `--cookie-file`, and `--proxy` for temporary overrides.

### 4. Verify the HTTP layer

```bash
curl -sS http://127.0.0.1:8081/v1/models
```

If API keys are configured, add:

```bash
-H 'Authorization: Bearer YOUR_BRIDGE_KEY'
```

Never paste bridge keys or Gemini session material into issues, logs, commits, or chat.

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

The same base URL can be used by OpenAI-compatible clients such as Hermes/OpenCode. See [`docs/clients.md`](docs/clients.md).

## Minimal curl test

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_BRIDGE_KEY' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8081/v1/chat/completions \
  -d '{
    "model": "gemini-3.1-pro",
    "messages": [{"role": "user", "content": "Reply with exactly: BRIDGE_OK"}],
    "stream": false
  }'
```

## Configuration

The complete reference is in [`docs/configuration.md`](docs/configuration.md). The important fields are:

| Field | Purpose |
|---|---|
| `port` | Local HTTP port; default `8081` |
| `host` | Bind address; default `0.0.0.0` |
| `upstream_backend` | `modern` by default; `legacy` is an explicit compatibility escape hatch |
| `cookie_file` | Local Gemini Web authentication file |
| `proxy` | Optional HTTP proxy; system proxy environment is also respected by the upstream client |
| `api_keys` | Local bridge authentication keys; empty disables bridge auth |
| `temporary_chats` | Request Gemini Web temporary chats when supported |
| `request_timeout_sec` | Upstream request timeout |
| `retry_attempts` | Bounded retry count |
| `prompt_soft_budget_chars` | Optional soft prompt budget |
| `tool_schema_budget_chars` | Tool-schema serialization budget |
| `planner_enabled` | Conservative Phase 7 planner experiment; disabled by default |

## Supported model aliases

The bridge exposes a stable client-facing model catalog. The modern Gemini Web transport maps its internal model tiers conservatively rather than depending on stale numeric deployment IDs.

| Client model | Intended role |
|---|---|
| `gemini-3.7-flash` | Flash tier |
| `gemini-3.6-flash` | Flash tier |
| `gemini-3.5-flash` | Flash-compatible alias |
| `gemini-3.5-flash-thinking` | Thinking-oriented client alias |
| `gemini-3.5-flash-thinking-lite` | Lightweight thinking alias |
| `gemini-3.1-pro` | Pro tier; requires an authenticated session where the upstream account permits it |
| `gemini-3.1-pro-enhanced` | Pro-oriented client alias |
| `gemini-auto` | Automatic tier selection |
| `gemini-flash-lite` | Lightweight Flash tier |

Do not treat these names as a guarantee of a particular Google backend deployment. Gemini Web can change its available models independently of this project.

## Tool calling

The bridge supports OpenAI-style function definitions and validates model-generated calls before returning them to the client. It can repair bounded formatting/schema errors, but it does not invent arbitrary tool intent and it never executes the tool itself.

That distinction is central to the project:

```text
Gemini → proposes tool call
Bridge → validates/normalizes/repairs
Hermes/OpenCode → executes tool
Hermes/OpenCode → returns observation
Bridge → preserves observation integrity
Gemini → chooses next action
```

## Streaming

Chat Completions streaming uses SSE. The package uses the modern upstream transport for generation and `httpx` for true downstream streaming where available.

A known implementation detail under active repair is that an upstream failure can currently occur after an initial SSE response header/chunk has been emitted. The repair branch tracks this as a transport/error-propagation issue; a partial stream must never be interpreted as a successful completed generation.

## Authentication/session handling

The bridge has two separate authentication layers:

1. **Bridge authentication** — optional local `api_keys` protecting the HTTP API.
2. **Gemini Web authentication** — the local session/cookie file consumed by the modern upstream client.

These are independent. A successful `/v1/models` response proves only that the bridge HTTP layer is reachable and, when configured, that bridge authentication succeeded. It does **not** prove that Gemini Web authentication is valid.

The repository's cookie-sync extension exports Gemini session data locally. Treat the exported file as a live credential:

- never print its contents;
- never paste it into an issue or chat;
- never commit it;
- use restrictive permissions such as `chmod 600`;
- rotate/re-export it if it is exposed.

## Docker

Docker support remains available, but authenticated Gemini Web sessions and proxy/network behavior are environment-sensitive. Mount configuration and authentication files read-only where practical and avoid baking session material into images.

```bash
cp config.example.json config.json
docker build -t gemini-web2api .
docker run --rm \
  -p 8081:8081 \
  -v "$PWD/config.json:/app/config.json:ro" \
  gemini-web2api
```

See [`docs/deployment.md`](docs/deployment.md) for container and host-network guidance.

## Troubleshooting

Start with [`docs/troubleshooting.md`](docs/troubleshooting.md). The most important diagnostic distinction is:

| Symptom | Likely layer |
|---|---|
| `/v1/models` works, generation says authentication/session failure | Gemini Web session |
| HTTP 405 mentioning `StreamGenerate` | old legacy process/transport |
| HTTP 429 from current upstream | Gemini upstream throttling/anti-abuse/session/network behavior |
| Bridge returns 401/403 before upstream request | local bridge authentication |
| Port 8081 already in use | another bridge process is running |
| Streaming starts then upstream fails | active stream error-propagation limitation |

When reporting a failure, provide redacted status codes, error types, timestamps, and the command shape. Never provide cookies, API keys, authorization headers, or session files.

## Development and verification

The project uses deterministic unit/regression tests plus explicit local real-client gates.

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall gemini_web2api scripts tests

git diff --check
```

The historical release-candidate gate also verifies trajectory/performance regressions and durable Hermes/OpenCode evidence. See [`docs/release-status.md`](docs/release-status.md) and [`docs/development.md`](docs/development.md).

## Project history

Phases 1–13 established the protocol, grounding, recovery, tool-choice, planner, real-client compatibility, trajectory benchmarking, observability, selective feature ports, stability, and independent release verification. The current repair branch adds the maintained Gemini Web transport after real-client testing exposed the stale direct `StreamGenerate` path.

The project is intentionally conservative: a passing synthetic test is not enough to claim that a live Gemini Web session works, and a model response is never treated as proof that a downstream tool executed.

## License

MIT. See [`LICENSE`](LICENSE).
