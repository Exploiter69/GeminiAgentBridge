# GeminiAgentBridge — Detailed Fixing Roadmap

> Status: engineering roadmap, based on the current repository audit.
>
> This document is intentionally a **plan**, not a claim that the listed fixes are already implemented.
>
> Primary target: make GeminiAgentBridge reliable infrastructure for OpenCode, Hermes, Codex-style and other OpenAI-compatible coding agents using Gemini Web as the model backend.

---

## 0. Non-negotiable architecture

```text
Coding agent (OpenCode / Hermes / Codex-style client)
                    |
                    | OpenAI-compatible HTTP
                    v
            GeminiAgentBridge
      +-------------------------------+
      | HTTP/API layer                |
      | request validation            |
      | authentication                |
      | OpenAI protocol normalization |
      | tool-call protocol            |
      | context management            |
      | SSE lifecycle                 |
      | retries/recovery              |
      | observability                 |
      +---------------+---------------+
                      |
                backend interface
                      |
             +--------+---------+
             |                  |
       Modern backend      Legacy backend
             |             (deprecated)
       gemini-webapi
             |
        Gemini Web

The bridge MUST NOT execute filesystem, shell, git, browser, or other agent tools.
The downstream agent remains the tool executor and owns the authoritative trajectory.
```

### Architectural rules

1. `repair-live-gemini-web` is the current release-candidate line until its work is merged into `main`.
2. Modern Gemini Web transport is the default and primary implementation.
3. Legacy `StreamGenerate` remains isolated and explicitly deprecated for compatibility only.
4. The bridge is stateless with respect to agent trajectories unless a feature explicitly requires otherwise.
5. The downstream agent owns tool execution and workspace state.
6. No credential/cookie/session values may appear in logs, errors, tests, fixtures, screenshots, or documentation.
7. Live Gemini Web success must never be claimed based only on offline tests.

---

# Phase 0 — Repository stabilization

**Priority: P0 / blocker**

## 0.1 Establish the release branch

- Treat `repair-live-gemini-web` as the working release candidate.
- Compare it against current `main` before every merge/rebase.
- Preserve useful historical tests and compatibility behavior, but do not restore obsolete production paths accidentally.
- Merge to `main` only after the P0/P1 gates below pass.

### Exit criteria

- `main` and release candidate agree on the intended 2.x architecture.
- A clean clone launches the modern backend by default.
- Legacy code cannot become the production path accidentally.

## 0.2 Repository inventory

Create/maintain a machine-readable inventory of:

- entrypoints
- packages
- transports
- configuration files
- test suites
- Docker files
- workflows
- extension
- Cloudflare/legacy components
- documentation
- compatibility aliases

### Exit criteria

Every executable path has an explicit owner, purpose, status, and deprecation state.

---

# Phase 1 — Security hardening

**Priority: P0 / do before live-agent exposure**

## 1.1 Safe network defaults

Change the default development bind from remote exposure to loopback.

Target:

```text
host = 127.0.0.1
```

For container/remote deployment:

```text
host = 0.0.0.0
API authentication = mandatory
```

### Exit criteria

- Unconfigured bridge is not remotely reachable.
- Remote bind without authentication is rejected at startup.

## 1.2 API authentication

Define one canonical authentication layer.

Requirements:

- constant-time API-key comparison
- no key values in logs
- missing/invalid key returns structured 401
- configuration validation rejects accidental insecure production mode
- compatibility aliases share the same auth middleware

## 1.3 SSRF protection

Remote image fetching must not allow arbitrary internal network access.

Implement:

- URL scheme allowlist: HTTP/HTTPS only
- reject localhost
- reject private IPv4 ranges
- reject loopback
- reject link-local
- reject multicast/reserved ranges
- reject private/loopback/link-local IPv6
- resolve DNS and validate every resolved address
- protect against DNS rebinding
- validate redirect destinations, not only the first URL
- use explicit connect/read timeouts

Prefer disabling remote image fetching by default if the feature is not required by target agents.

### Exit criteria

Automated tests prove requests to loopback/private/link-local addresses are blocked.

## 1.4 Bound request bodies

Add a configurable hard limit before reading `Content-Length` bytes.

Target behavior:

```text
413 Payload Too Large
```

for oversized requests.

Also protect chunked/unknown-length bodies if supported.

## 1.5 Bound remote image downloads

Do not call unbounded `read()` on arbitrary remote resources.

Implement:

- maximum image bytes
- streaming read in bounded chunks
- Content-Length pre-check when available
- hard timeout
- decompression/resource protections if applicable

## 1.6 Remove secret-bearing logs

Never log:

- cookies
- session tokens
- Authorization values
- API keys
- upload-session URLs
- full proxy URLs containing credentials
- Gemini authentication material

Replace diagnostic URL logging with opaque IDs or event names.

## 1.7 Error redaction

Client-facing errors must use stable categories rather than raw exception strings.

Example:

```json
{
  "error": {
    "type": "upstream_authentication_error",
    "message": "The Gemini Web session is not authenticated."
  }
}
```

Detailed exception data stays in protected server logs.

### Phase 1 exit gate

```text
[ ] loopback default
[ ] remote auth required
[ ] SSRF tests pass
[ ] request size limit pass
[ ] image size limit pass
[ ] secret-log scan pass
[ ] error-redaction tests pass
```

---

# Phase 2 — Modern Gemini Web backend correctness

**Priority: P0**

## 2.1 Define backend interface

Create one explicit interface for unary and streaming generation.

Conceptually:

```text
Backend.generate(request) -> normalized result
Backend.stream(request) -> async/sync stream of normalized events
Backend.health() -> backend status
Backend.close() -> graceful shutdown
```

The HTTP layer must not know `gemini-webapi` internals.

## 2.2 GeminiClient lifecycle

Use one documented lifecycle:

```text
initialize
  -> authenticate
  -> serve
  -> refresh/reinitialize on recoverable session failure
  -> close
```

Do not simply drop the client reference during shutdown.

Explicitly close the upstream client before stopping the background loop.

## 2.3 Concurrency policy

The bridge currently uses a long-lived Gemini client from a multithreaded HTTP server.

Choose and document one model:

### Initial recommended model

```text
HTTP worker threads
        |
        v
one background asyncio loop
        |
     asyncio.Lock
        |
  shared GeminiClient
```

This prioritizes correctness.

Only remove serialization after real concurrency testing demonstrates that `gemini-webapi` safely supports concurrent calls for the exact operations used.

## 2.4 Cancellation

Client disconnect must propagate toward the upstream generation where possible.

Required behavior:

```text
agent disconnects
   -> HTTP stream closes
   -> bridge cancellation event
   -> upstream generation cancelled
   -> resources released
```

Add tests for:

- disconnect before first token
- disconnect during stream
- disconnect after tool-call detection
- shutdown during generation

## 2.5 Session health/recovery

Classify upstream failures:

```text
AUTH_EXPIRED
AUTH_INVALID
RATE_LIMIT
TEMPORARY_UPSTREAM
TIMEOUT
NETWORK
PROTOCOL
MODEL_UNAVAILABLE
UNKNOWN
```

Only retry errors classified as safe.

Authentication failures should trigger controlled reinitialization/refresh rather than an unlimited retry loop.

## 2.6 Retry policy

Define one bounded policy with:

- max attempts
- exponential backoff
- jitter
- retryable exception classes
- retry-after support where available
- no retry after unsafe semantic output

### Agent-specific rule

```text
No model output yet       -> retry may be safe
Natural-language output   -> do not blindly regenerate
Tool call observed        -> do not blindly regenerate
Tool execution in progress -> never duplicate through retry
```

## 2.7 Model resolution

Unknown model IDs should not silently fall back in the default mode.

Preferred:

```text
known model -> mapped Gemini model
unknown     -> structured 400
```

Optional explicit compatibility mode may retain fallback behavior.

## 2.8 Temporary-chat policy

Default to temporary Gemini conversations unless persistent Gemini history is explicitly requested.

This keeps agent trajectories owned by the downstream client and avoids uncontrolled Gemini account history growth.

### Phase 2 exit gate

```text
[ ] backend interface isolated
[ ] client close works
[ ] concurrency policy documented/tested
[ ] cancellation tests pass
[ ] auth refresh/reinit tests pass
[ ] retry matrix passes
[ ] unknown-model behavior is deterministic
```

---

# Phase 3 — Streaming/SSE correctness

**Priority: P0**

## 3.1 Preflight before HTTP commit

Do not send the initial SSE response merely because the request parsed successfully.

Preferred flow:

```text
HTTP request
   -> validate
   -> auth
   -> backend/session health
   -> start upstream generation
   -> receive first meaningful upstream event
   -> commit HTTP 200 + SSE
   -> flush buffered first event
   -> continue
```

This provides a clean HTTP error for failures that happen before the first model event.

## 3.2 Post-commit failures

Once SSE is committed, HTTP status cannot be changed.

Therefore define an explicit terminal stream-error event.

Do NOT emit `[DONE]` after a failed stream as if the generation succeeded.

Document the exact event schema and test OpenAI-compatible clients against it.

## 3.3 Empty upstream stream

Define behavior for:

```text
upstream opens
no deltas
stream ends
```

It must produce a deterministic valid response rather than hanging or emitting an invalid trajectory.

## 3.4 Finish reasons

Map:

```text
stop
length
tool_calls
content_filter / safety where applicable
error
```

to stable OpenAI-compatible values.

## 3.5 Usage reporting

Define whether usage is:

- exact
- estimated
- unavailable

Never fabricate token counts.

If unavailable, omit usage or return explicit null semantics supported by the client.

### Phase 3 exit gate

```text
[ ] pre-first-token auth failure returns HTTP error
[ ] pre-first-token timeout returns HTTP error
[ ] mid-stream failure produces terminal stream error
[ ] no false [DONE] after failure
[ ] client disconnect cancels upstream
[ ] empty stream deterministic
[ ] finish_reason deterministic
```

---

# Phase 4 — OpenAI protocol normalization

**Priority: P0/P1**

Create one canonical internal representation independent of HTTP API version.

```text
OpenAI request
    -> InternalRequest
        -> BackendRequest

BackendResponse
    -> InternalResponse
        -> OpenAI Chat/Responses response
```

## 4.1 Chat Completions

Verify:

- system
- developer where applicable
- user
- assistant
- tool
- empty content
- Unicode
- multimodal content
- repeated turns
- multiple tool calls
- tool results
- finish reasons
- IDs
- timestamps
- model field

## 4.2 `/v1/models`

Return stable model metadata.

Do not advertise capabilities that the backend cannot actually provide.

## 4.3 `/v1/responses`

Keep this explicitly documented as a supported subset until all required semantics are implemented.

Do not claim full Responses API compatibility prematurely.

## 4.4 Request validation

Return structured 400 errors for:

- missing messages/input
- invalid role
- invalid tool schema
- malformed JSON arguments
- unsupported parameter
- unsupported model
- invalid tool choice

### Phase 4 exit gate

Run a protocol test matrix against a real OpenAI-compatible client/SDK, not only handcrafted curl requests.

---

# Phase 5 — Agent/tool protocol

**Priority: P0/P1**

## 5.1 One canonical tool-call representation

Normalize all accepted Gemini outputs into:

```text
ToolCall {
  id
  name
  arguments_json
}
```

The bridge must never expose internal sentinel formats to downstream agents.

## 5.2 Parsing

Support only intentionally documented formats:

- canonical structured form
- compatibility fenced form
- raw JSON compatibility form if required

Order parsing deterministically.

## 5.3 Validation

Validate:

- tool name exists
- arguments are valid JSON
- arguments conform to schema where available
- tool ID is stable
- no unexpected duplicate IDs
- no impossible assistant/tool message ordering

## 5.4 Repair

Repair is allowed only for syntax/protocol invalidity.

Repair must not silently change the user's task.

Add tests that prove:

```text
invalid JSON -> repaired JSON
wrong tool name -> rejected
missing required arg -> rejected/repaired
semantic tool substitution -> rejected
```

## 5.5 Multiple/parallel calls

Test:

```text
one call
2 sequential calls
2 parallel calls
5 calls
mixed tool + text
```

Define whether the bridge preserves parallel tool calls or serializes them.

## 5.6 Tool-result round trips

Validate the full trajectory:

```text
assistant tool call
 -> downstream execution
 -> tool message
 -> assistant continuation
```

The bridge must preserve ordering and IDs exactly.

## 5.7 Retry safety

Never regenerate a request in a way that can produce a second logically identical tool call after the first tool call has already been surfaced.

---

# Phase 6 — Context and long-running trajectories

**Priority: P1**

## 6.1 Make context budget real

Wire configured context limits into the actual request path.

Do not keep dead configuration values.

## 6.2 Preserve critical messages

Compaction should preserve:

1. system/developer instructions
2. current user task
3. active tool call/result state
4. recent assistant/tool trajectory
5. required repository/task context

## 6.3 Never invent workspace state

The bridge must not claim it inspected files.

Workspace state comes from agent tools.

## 6.4 Context stress tests

Test trajectories of:

```text
10 turns
20 turns
50 turns
100 turns
large tool outputs
large file contents
repeated edits
```

Measure prompt size, latency, failure rate, and compaction correctness.

---

# Phase 7 — Observability and diagnostics

**Priority: P1**

Implement structured request lifecycle events:

```text
request_received
request_validated
backend_started
backend_retry
backend_auth_failure
first_token
tool_call_detected
stream_error
request_completed
request_cancelled
```

Each request gets a non-secret trace ID.

Never log request bodies or credentials by default.

Metrics should include:

- request count
- success/failure
- latency
- time-to-first-token
- upstream retries
- auth failures
- rate limits
- cancellations
- stream failures
- tool-call parse failures

### Exit criteria

A single failed agent request can be diagnosed from logs without exposing its prompt, cookies, or credentials.

---

# Phase 8 — Packaging and deployment

**Priority: P1**

## 8.1 Package identity

Primary:

```text
gemini-agent-bridge
```

Preferred CLI:

```text
gemini-agent-bridge
```

Compatibility CLI:

```text
gemini-web2api
```

## 8.2 Python support

CI/test:

```text
3.11
3.12
3.13
3.14
```

## 8.3 Clean installation

Verify from a clean environment:

```bash
python -m venv .venv
pip install .
gemini-agent-bridge --help
```

No repository checkout assumptions.

## 8.4 Docker

Docker must:

- install the modern dependency set
- launch the modern backend
- use safe configuration
- avoid embedding secrets
- expose the intended port
- support graceful SIGTERM
- provide health checks

## 8.5 Compose

Rename primary service/container branding to GeminiAgentBridge while retaining compatibility aliases only where useful.

---

# Phase 9 — Extension/session sync

**Priority: P1**

Audit the extension independently.

Verify:

- Manifest validity
- least-privilege permissions
- correct Gemini host permissions
- cookie access limited to required domains/names
- export format exactly matches `modern.py`
- no session values logged
- no session values displayed unnecessarily
- download behavior works
- branding is GeminiAgentBridge

The extension must never become a second source of truth for authentication logic.

---

# Phase 10 — Legacy isolation

**Priority: P1**

Keep legacy code available only when explicitly selected.

Requirements:

```text
upstream_backend = modern    # default
upstream_backend = legacy    # explicit compatibility/debug only
```

Legacy code must:

- be clearly labeled
- have separate tests
- not be imported into modern execution paths unnecessarily
- not be used by Docker/default CLI
- be documented as deprecated

Cloudflare worker belongs here unless it is deliberately revived later.

---

# Phase 11 — Remove import-time monkey patching

**Priority: P1**

Replace:

```text
_tools.messages_to_prompt = ...
_tools.parse_tool_calls = ...
_gemini.generate = ...
```

with explicit protocol/backend composition.

Target dependency flow:

```text
server
  -> protocol
      -> backend
```

No hidden global mutation during import.

This should be done only after the current behavior is protected by tests.

---

# Phase 12 — Real agent validation

**Priority: P0 release gate**

This is the most important test phase after code hardening.

Use a fresh authenticated Gemini Web session.

## OpenCode

Test:

1. inspect repository
2. explain architecture
3. modify one file
4. add a feature
5. run tests
6. diagnose failing test
7. modify multiple files
8. git diff review
9. long tool trajectory
10. cancellation/retry

## Hermes

Repeat the equivalent trajectory matrix.

## Third agent

Use another OpenAI-compatible coding agent to ensure the implementation isn't accidentally tailored to one client.

### Required evidence

Record:

- exact bridge version/commit
- backend version
- client version
- model mapping
- number of requests
- number of tool calls
- stream failures
- retries
- latency
- final task success

Never record credentials.

---

# Phase 13 — Reliability/stress testing

**Priority: P1**

## Sequential load

Run:

```text
10 requests
50 requests
100 requests
```

and measure:

- memory
- open sockets
- latency
- error rate
- session stability

## Concurrent load

Test 2/4/8/16 simultaneous requests.

The expected behavior must be deterministic even if concurrency is deliberately serialized initially.

## Fault injection

Simulate:

- expired session
- network timeout
- 429
- 500
- malformed upstream chunk
- connection reset
- client disconnect
- shutdown during generation

No request should leave the bridge in a corrupted state.

---

# Phase 14 — Documentation and branding

**Priority: P1**

Update all primary documentation to consistently say:

```text
GeminiAgentBridge
```

Search globally for:

```text
gemini-web2api
Sophomoresty
Forked from
old repository URLs
StreamGenerate
```

Classify each occurrence as:

1. compatibility
2. legacy
3. historical
4. accidental

Remove only category 4.

Primary README must explain:

- what GeminiAgentBridge is
- what it is not
- modern transport
- legacy transport
- security model
- authentication/session setup without publishing credentials
- OpenAI compatibility scope
- tool-calling behavior
- known limitations
- real-agent validation status

---

# Phase 15 — CI/release gates

**Priority: P1**

Every PR must run:

```text
pytest
compileall
package build
installation test
Python 3.11–3.14 matrix
credential scan
Docker build
```

Optional protected live workflow:

```text
fresh authenticated session
modern backend smoke test
stream smoke test
```

Live tests must never print secrets.

---

# Final release checklist

## Repository

- [ ] modern implementation is on `main`
- [ ] old implementation cannot accidentally become default
- [ ] branding is correct
- [ ] compatibility aliases documented

## Security

- [ ] loopback default
- [ ] remote authentication mandatory
- [ ] SSRF blocked
- [ ] request size bounded
- [ ] image size bounded
- [ ] secret logs eliminated
- [ ] raw upstream errors redacted

## Transport

- [ ] authenticated generation works
- [ ] authenticated streaming works
- [ ] client lifecycle is clean
- [ ] concurrency is deterministic
- [ ] cancellation works
- [ ] recovery works
- [ ] retry policy is agent-safe

## Protocol

- [ ] Chat Completions compatibility tested
- [ ] Responses subset tested
- [ ] SSE tested
- [ ] finish reasons correct
- [ ] tool calls correct
- [ ] tool results correct
- [ ] multi-tool trajectories correct

## Agents

- [ ] OpenCode real-client gate passed
- [ ] Hermes real-client gate passed
- [ ] third OpenAI-compatible agent passed
- [ ] long trajectory passed
- [ ] cancellation passed
- [ ] recovery passed

## Packaging

- [ ] clean pip install
- [ ] CLI works
- [ ] compatibility CLI works
- [ ] Docker works
- [ ] Compose works
- [ ] CI green

## Documentation

- [ ] README current
- [ ] architecture current
- [ ] security current
- [ ] live-transport status honest
- [ ] known limitations explicit

---

# Implementation order

Do not fix files randomly. Use this order:

```text
P0. Repository/release-line stabilization
        ↓
P0. Security hardening
        ↓
P0. Modern backend lifecycle/concurrency
        ↓
P0. SSE lifecycle + cancellation
        ↓
P0. Tool-call retry safety
        ↓
P1. OpenAI protocol normalization
        ↓
P1. Context management
        ↓
P1. Observability
        ↓
P1. Packaging/Docker/extension
        ↓
P1. Remove monkey patches
        ↓
P0. Fresh authenticated live transport test
        ↓
P0. OpenCode + Hermes + third-agent tests
        ↓
P1. Stress/fault injection
        ↓
Release
```

## Rule for every fix

For each change:

1. Add or update a regression test first when practical.
2. Make the smallest architectural change that fixes the root cause.
3. Run focused tests.
4. Run the full offline suite.
5. Run security/credential scans.
6. Only then move to the next phase.
7. Never claim live Gemini functionality until the live gate passes with a fresh authenticated session.
