# GeminiAgentBridge — Capability Preservation & Fix Roadmap

> **Status:** active engineering plan
>
> **Purpose:** repair GeminiAgentBridge after the original `gemini-web2api` architecture audit, while preserving useful upstream capabilities instead of replacing one limitation with another.
>
> **Baseline:** `main` at `d217f2a` (`fix: activate tool-call recovery in production launcher`).
>
> **Important:** this document is a plan. A checked item means the implementation and its regression tests are complete; tests alone are not sufficient when a live Gemini Web capability is involved.

---

## 1. Goal

GeminiAgentBridge exists to provide a reliable OpenAI-compatible HTTP interface over Gemini Web for agentic clients such as Hermes, OpenCode, Codex-style clients, and other coding agents.

The target is **not** merely to make one demo request succeed. The target is:

```text
OpenAI-compatible agent
        |
        v
GeminiAgentBridge
        |
        +-- request/protocol normalization
        +-- security boundaries
        +-- tool-call protocol recovery
        +-- streaming/SSE correctness
        +-- context management
        |
        v
Backend abstraction
        |
        +-- Modern Gemini Web backend (primary)
        +-- Legacy backend (compatibility/deprecated)
        |
        v
Gemini Web
```

The downstream agent remains the owner of:

- filesystem operations
- shell commands
- git operations
- browser actions
- tool execution
- workspace state
- authoritative agent trajectory

The bridge translates and transports requests; it must not silently invent workspace state or execute downstream agent tools.

---

# 2. Audit conclusions — what must be fixed

The repository audit compared the original `Sophomoresty/gemini-web2api` implementation with GeminiAgentBridge. The major conclusion is:

> The modernization direction is correct, but the modern backend was implemented too narrowly and silently dropped capabilities that existed in the original path.

### Confirmed issues

| ID | Issue | Priority | State |
|---|---|---:|---|
| CP-01 | Modern backend drops uploaded `file_refs` / multimodal inputs | P0 | Open |
| CP-02 | Model catalog advertises distinctions that modern transport collapses | P0 | Open |
| CP-03 | Thinking/reasoning model semantics are not preserved end-to-end | P0 | Open |
| CP-04 | Backend interface does not preserve all original request capabilities | P0 | Open |
| CP-05 | Tool-call recovery is bounded recovery, not a guarantee of valid generation | P1 | Document/verify |
| CP-06 | Raw tool-call fallback relies on fragile regex-style JSON extraction | P1 | Open |
| CP-07 | Schema compaction may remove semantically useful fields such as `default` | P1 | Open |
| CP-08 | Context compaction exists but is not a complete/default long-context solution | P1 | Open |
| CP-09 | Phase 10+ code exists but is not necessarily installed in production | P1 | Open |
| CP-10 | Observability implementation and production activation/documentation are not fully aligned | P1 | Open |
| CP-11 | Top-level launcher/module compatibility changed and needs explicit documentation/tests | P1 | Open |
| CP-12 | Full agentic compatibility has not been demonstrated against real Gemini Web failure cases | P0 | Open |

### Changes we should keep

These were improvements rather than mistakes:

- loopback-safe default binding
- mandatory authentication for remote binding
- constant-time API-key comparison
- SSRF protections
- bounded request/image bodies
- secret-safe diagnostics
- structured error handling
- long-lived modern async client lifecycle
- explicit production activation of Phase 4/5/6 recovery
- strict tool-schema validation
- downstream ownership of tool execution

Do **not** revert these merely to recover historical behavior.

---

# 3. Non-negotiable engineering rules

1. **Preserve capability before adding features.** Every modernization change must be checked against the original behavior and the maintained `gemini-webapi` client capabilities.
2. **No silent fallback.** A requested model or capability must not quietly become a different model/capability unless compatibility fallback is explicitly requested.
3. **No fabricated semantics.** Do not invent token counts, model capabilities, tool arguments, tool results, workspace state, or reasoning metadata.
4. **Bounded recovery only.** Recovery may repair protocol/syntax failures but must not turn into uncontrolled regeneration.
5. **Tool execution belongs downstream.** The bridge returns tool calls; it does not execute them.
6. **Never duplicate a side-effecting tool call because of transport retry.** Retry decisions must account for trajectory state.
7. **No credential material in logs, tests, fixtures, docs, screenshots, or commits.**
8. **Live claims require live evidence.** Offline tests prove code behavior, not Gemini Web availability.
9. **Production activation must be explicit.** A phase installer existing in the repository does not mean that phase is active.
10. **Every compatibility claim must have a test.**
11. **Prefer an explicit unsupported response over silently degrading a request.**
12. **Do not delete the legacy path until compatibility coverage proves it is no longer required.**

---

# 4. Phase 0 — Freeze and establish the audit baseline

**Priority: P0 — do first**

## 4.1 Preserve current known-good baseline

Baseline commit:

```text
d217f2a fix: activate tool-call recovery in production launcher
```

Before modifying code:

```bash
git status --short
git log --oneline --decorate -5
pytest -q
```

Expected baseline:

```text
167 passed, 5 subtests passed
```

Keep the existing stash untouched until the capability audit is complete. Do not blindly restore it.

## 4.2 Build a capability inventory

For every request feature, record:

```text
OpenAI input
 -> server normalization
 -> internal representation
 -> backend adapter
 -> gemini-webapi call
 -> Gemini Web behavior
 -> normalized response
 -> OpenAI output
```

Inventory at minimum:

- text messages
- system/developer messages
- images
- files/documents
- model ID
- thinking/reasoning options
- tool definitions
- tool choice
- multiple tool calls
- tool results
- streaming
- temporary conversation mode
- grounding/search options where supported
- response metadata
- finish reasons
- usage information
- cancellation
- errors

### Exit gate

No request parameter is allowed to disappear silently between API and backend.

---

# 5. Phase 1 — Backend abstraction and capability preservation

**Priority: P0 — highest implementation priority**

This is the central correction.

## 5.1 Define an internal request model

Introduce a normalized internal request representation conceptually equivalent to:

```text
InternalRequest
├── messages
├── model
├── stream
├── files/images
├── tools
├── tool_choice
├── generation options
├── thinking/reasoning options
├── temporary
├── grounding/search options
└── provider-specific extensions
```

The HTTP layer must not directly depend on `gemini-webapi` internals.

## 5.2 Define a backend interface

Conceptually:

```text
Backend
├── capabilities()
├── resolve_model(requested_model)
├── generate(request)
├── stream(request)
├── health()
└── close()
```

The exact Python API can differ, but capability ownership must be explicit.

## 5.3 Capability negotiation

Every backend must report what it can actually do.

Example:

```text
text                 yes
streaming            yes
images               yes/no
files                yes/no
thinking             yes/no
multiple_tool_calls  yes/no
native_tools         yes/no
responses_api        subset/full
```

The API layer uses this matrix to reject unsupported requests instead of silently degrading them.

---

# 6. Phase 2 — Fix multimodal/file forwarding

**Priority: P0**

## Problem

The server can upload/prepare images and produce file references, but the current modern transport path does not preserve those references when calling the modern Gemini client.

Conceptually the broken path is:

```text
OpenAI image/file
   -> upload
   -> file_refs
   -> modern.generate(prompt, model)
   -> file_refs discarded
```

## Required fix

Preserve the complete multimodal request through the backend abstraction.

Verify the maintained Gemini Web client API for the exact supported file/image argument shape before implementation. Do not guess a parameter name.

Support, where the backend permits:

- image URLs/data
- uploaded files
- documents
- multiple attachments
- MIME types
- attachment ordering
- attachment + text combinations
- streaming with attachments

## Tests

Add mocked backend tests proving:

```text
input image -> backend receives image/file reference
multiple images -> order preserved
file + text -> both preserved
large/invalid attachment -> deterministic error
```

Add a live smoke test only after mocked coverage is complete.

### Exit gate

No attachment is silently discarded.

---

# 7. Phase 3 — Correct model resolution

**Priority: P0**

## Problem

The public model catalog contains several model IDs and thinking variants, while the modern backend currently collapses many of them to broad Flash/Pro modes.

That creates false capability claims.

## Required design

Separate three concepts:

```text
requested bridge model ID
        ↓
model resolver
        ↓
actual account-available Gemini model
```

Use the maintained Gemini Web client/account model discovery where possible.

## Rules

### Known model

Resolve deterministically.

### Unknown model

Return a structured unsupported/invalid-model response by default.

### Compatibility alias

Only use fallback when the model catalog explicitly marks the ID as an alias.

### Account unavailable

If a model is not available to the authenticated Gemini account, report that instead of pretending another model was used.

## Model metadata

Do not advertise:

- thinking support
- context limits
- multimodal support
- streaming
- model identity

unless the selected backend actually supports them.

## Tests

- every advertised model resolves
- unknown model rejected
- alias behavior explicit
- model field in response matches actual selected model
- account-unavailable model handled deterministically

### Exit gate

The API model catalog and backend behavior describe the same capabilities.

---

# 8. Phase 4 — Preserve thinking/reasoning semantics

**Priority: P0**

Audit the original model configuration and current modern client for:

- thinking modes
- reasoning effort
- model-specific generation options
- extra fields
- temporary mode
- provider-specific options

Create an explicit mapping table:

```text
Bridge option
 -> modern client equivalent
 -> legacy equivalent
 -> unsupported behavior
```

If a modern Gemini Web model does not expose an equivalent, do not silently claim that the option is active.

Possible behavior:

```text
supported -> pass through
unsupported optional -> ignore only in explicit compatibility mode
unsupported required -> structured 400
```

## Tests

Mock the backend and assert every supported reasoning/thinking field reaches the adapter.

For unsupported options, assert deterministic behavior.

### Exit gate

`thinking` model IDs no longer mean only "select some Flash model".

---

# 9. Phase 5 — Tool-call protocol redesign and recovery

**Priority: P0/P1**

The original failure remains central:

```text
Gemini malformed tool call
        ↓
parse_tool_calls()
        ↓
ValueError
        ↓
HTTP 500
```

Our Phase 4/5/6 runtime now catches this class of failure in the production launcher. Keep that fix.

But improve the layer carefully.

## 9.1 Canonical representation

Internally normalize to:

```text
ToolCall
├── id
├── name
└── arguments_json
```

Downstream agents must never receive internal sentinel syntax.

## 9.2 Parsing order

Use deterministic parsing:

1. canonical structured/sentinel format
2. fenced compatibility format
3. brace-aware raw JSON compatibility parser
4. otherwise treat as ordinary text / repair candidate according to tool choice

## 9.3 Replace fragile raw JSON extraction

Do not use a simple non-greedy regex as the primary raw JSON parser.

Implement a brace/string-aware scanner that understands:

- nested objects
- nested arrays
- escaped quotes
- escaped backslashes
- braces inside strings
- multiple JSON objects

## 9.4 Schema validation

Validate:

- known tool
- valid JSON arguments
- required fields
- types
- enums
- additional properties
- tool-call IDs
- tool/message ordering

## 9.5 Recovery policy

Recovery is for protocol/syntax errors, not arbitrary model misunderstanding.

Examples:

```text
malformed JSON          -> repair candidate
missing required arg    -> repair candidate
wrong tool under named choice -> repair candidate
unknown tool             -> reject/repair depending on context
semantic task failure    -> do not blindly regenerate
```

Keep repair bounded.

Recommended initial policy:

```text
original generation: 1
repair generation:   1
```

Only increase after evidence and explicit safety analysis.

## 9.6 Tool-choice semantics

Correctly support:

```text
auto
none
required
named function
```

`none` must not expose tools to the model.

`required` must produce a tool call when tools exist.

Named choice must produce the requested tool or fail deterministically.

## 9.7 Parallel/multiple calls

Preserve order and IDs for multiple calls.

Explicitly test:

```text
1 call
2 calls
5 calls
parallel calls
duplicate calls
mixed text + tool calls
```

### Exit gate

The previous malformed-tool-call 500 becomes a bounded protocol recovery/failure rather than an opaque server crash.

---

# 10. Phase 6 — Schema compaction without semantic loss

**Priority: P1**

Schema compaction is useful for large agent toolsets, but must not change the meaning of the schema.

## Preserve semantic fields

At minimum audit preservation of:

- type
- properties
- required
- enum
- items
- additionalProperties
- nullable/union semantics
- default where meaningful
- constraints used for argument validity

Only remove metadata that is proven irrelevant to the model/tool protocol.

## Tests

Build before/after semantic comparisons.

For each compacted schema, validate the same accepted/rejected argument examples against the original and compacted form.

### Exit gate

Compaction reduces prompt size without changing tool validity semantics.

---

# 11. Phase 7 — Context and long-horizon agent trajectories

**Priority: P1**

The current compactor is a mechanism, not proof that long-running coding sessions are solved.

## 11.1 Define context budget

Use explicit configurable limits for:

- prompt characters/tokens
- tool definitions
- tool outputs
- file contents
- total trajectory

## 11.2 Preserve critical state

Compaction priority:

1. system/developer instructions
2. current user task
3. active tool calls and tool results
4. recent assistant trajectory
5. recent user context
6. older history

Never invent a summary that claims facts not present in the source trajectory.

## 11.3 Tool-output handling

Large outputs should be bounded and, where possible, summarized by the downstream agent/tool rather than silently truncated by the bridge.

If the bridge truncates, mark it explicitly.

## 11.4 Stress tests

Test:

```text
10 turns
20 turns
50 turns
100 turns
large files
large tool output
many tool calls
repeated edit/test loops
```

Measure:

- prompt size
- latency
- failure rate
- tool-call accuracy
- context-loss incidents

### Exit gate

Long trajectories degrade predictably rather than failing because of hidden hard limits.

---

# 12. Phase 8 — Streaming/SSE correctness

**Priority: P0**

Streaming is part of agent compatibility, not an optional presentation feature.

## Required lifecycle

```text
HTTP request
 -> validate/auth
 -> backend preflight
 -> upstream generation
 -> first meaningful event
 -> commit SSE
 -> stream events
 -> terminal success/error
```

## Rules

Before HTTP headers are committed, failures should remain normal HTTP errors.

After commitment, HTTP status cannot change, so emit an explicit terminal stream error event.

Never emit successful `[DONE]` semantics after an upstream failure.

Test:

- auth failure before first event
- timeout before first event
- upstream 429
- upstream 5xx
- malformed tool call during stream
- disconnect mid-stream
- shutdown mid-stream
- empty stream
- finish reasons
- multiple tool-call deltas

### Exit gate

OpenAI-compatible streaming clients can distinguish success from failure without guessing.

---

# 13. Phase 9 — Chat Completions and Responses API normalization

**Priority: P0/P1**

Create one internal representation and map it outward.

```text
Chat Completions ─┐
                  ├─> InternalRequest/Response ─> Backend
Responses API ────┘
```

## Chat Completions matrix

Verify:

- system
- developer
- user
- assistant
- tool
- empty content
- Unicode
- multimodal content
- multiple tool calls
- tool results
- model
- finish reason
- stream/non-stream
- IDs
- timestamps

## Responses API

Keep the supported subset explicit.

Do not claim full Responses API compatibility until the complete required lifecycle is implemented and tested.

## `/v1/models`

Model metadata must match the actual backend capability registry.

### Exit gate

A real OpenAI-compatible SDK can use both supported endpoints without provider-specific hacks.

---

# 14. Phase 10 — Session health, retries, and cancellation

**Priority: P1**

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
CANCELLED
UNKNOWN
```

## Retry safety

Retry only safe failures.

```text
No output yet            -> retry may be safe
Natural-language output  -> normally do not regenerate
Tool call surfaced       -> do not regenerate
Tool execution underway  -> never duplicate
```

Use:

- bounded attempts
- exponential backoff
- jitter
- Retry-After when valid
- cancellation propagation

## Client lifecycle

Maintain one explicit lifecycle:

```text
initialize
 -> serve
 -> recover/reinitialize when safe
 -> close
```

Ensure the async loop and Gemini client are both closed during shutdown.

### Exit gate

No retry can accidentally execute the same side-effecting tool twice.

---

# 15. Phase 11 — Observability and diagnostics

**Priority: P1**

The existing observability implementation should be kept, but production activation must be reconciled with the documentation.

Safe lifecycle events should include at least:

```text
request_received
context_built
prompt_built
upstream_request
upstream_response
candidate_tool_call
parsed_tool_call
schema_validation
repair_attempt
client_tool_call_returned
observation_received
observation_validated
next_turn
request_completed
request_failed
```

Each request gets a non-secret trace ID.

Never log:

- prompts
- model responses
- tool arguments
- cookies
- API keys
- authorization headers
- session tokens

unless a future explicitly opt-in secure diagnostic mode is designed and reviewed.

## Production activation decision

Choose one of:

1. install Phase 10 by default after performance/security validation, or
2. keep it opt-in and clearly document that behavior.

Do not leave the repository ambiguous.

### Exit gate

A failed request can be diagnosed using event metadata without exposing credentials or content.

---

# 16. Phase 12 — Legacy backend compatibility

**Priority: P1**

Legacy is deprecated, but must remain internally coherent until removal is intentional.

Audit:

- startup requirements
- model mapping
- files
- streaming
- tool calls
- errors
- authentication
- shutdown

The legacy backend must not accidentally become the default modern production path.

If removed later, document the exact breaking changes.

### Exit gate

Legacy behavior is either tested/deprecated or explicitly removed; there is no accidental half-supported state.

---

# 17. Phase 13 — Packaging, launcher, and compatibility

**Priority: P1**

## Entrypoints

Document the supported commands:

```bash
python -m gemini_web2api
```

and the preferred installed CLI once finalized.

If `gemini_web2api.py` remains as a compatibility wrapper, explicitly test that it launches the same supported application.

## Clean installation

Test from a clean virtual environment:

```bash
python -m venv .venv
pip install .
python -m gemini_web2api --help
```

## Python matrix

Test supported Python versions explicitly rather than assuming local Python compatibility.

## Docker

Verify:

- modern backend dependency set
- safe bind/auth configuration
- no embedded credentials
- health check
- graceful SIGTERM
- intended port

### Exit gate

A clean checkout behaves the same way as the development checkout for all documented commands.

---

# 18. Phase 14 — Cookie/session extension audit

**Priority: P1**

Audit the browser extension independently from the server.

Verify:

- manifest permissions are minimal
- Gemini/Google host permissions are intentional
- cookie selection is deterministic
- exported fields match the modern backend contract
- no credentials are logged or unnecessarily displayed
- export file is clearly marked sensitive
- server documentation matches extension output
- stale/unused legacy fields are not required by the modern path

Do not make authentication fixes by weakening browser security.

### Exit gate

The extension and modern backend have one documented session contract.

---

# 19. Phase 15 — Test architecture upgrade

**Priority: P0/P1**

The existing suite is strong for pure logic and currently passes:

```text
167 passed, 5 subtests passed
```

But that does not prove live Gemini Web behavior.

Build four test layers.

## Layer A — Pure unit tests

Fast deterministic tests for:

- parsing
- schemas
- model resolution
- protocol normalization
- security
- SSRF
- compaction
- retry classification

## Layer B — Backend contract tests

Mock the Gemini Web client and verify every internal request field reaches the adapter correctly.

Especially:

```text
model
files
images
thinking
temporary
tools
tool_choice
stream
```

## Layer C — HTTP integration tests

Run the actual bridge HTTP server and test:

- Chat Completions
- Responses
- `/v1/models`
- SSE
- errors
- auth
- cancellation

## Layer D — Live Gemini Web tests

Use the authenticated local environment without exposing session material.

Required live scenarios:

1. basic text
2. sequential requests
3. streaming
4. image/file input
5. model selection
6. tool call
7. multiple tool calls
8. tool-result continuation
9. malformed tool-call recovery
10. long agentic task
11. failure/recovery
12. Hermes/OpenCode integration

Live results must be recorded as evidence, not assumed from unit tests.

---

# 20. Phase 16 — Real agent compatibility matrix

**Priority: P0 release gate**

Test actual clients, not only curl.

| Client | Basic | Tools | Multi-tool | Streaming | Long task | Tool results | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Hermes | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | pending |
| OpenCode | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | pending |
| Codex-style client | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | pending |
| Generic OpenAI SDK | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | pending |

The previous Hermes failure must become a mandatory regression test:

```text
Gemini emits malformed tool call
 -> bridge recovers once
 -> valid tool call returned
 -> agent executes it
 -> observation returned
 -> next assistant turn succeeds
```

Also test the failure case:

```text
Gemini malformed call
 -> repair malformed again
 -> bounded failure
 -> agent receives explicit provider error
 -> no infinite loop
```

---

# 21. Phase 17 — Performance and stability

**Priority: P1**

Measure before optimizing.

Metrics:

- request latency
- time to first token
- stream duration
- prompt construction time
- model resolution time
- repair frequency
- retry frequency
- memory usage
- concurrent request behavior
- context-compaction cost

The current single-client/async-lock design should remain until concurrency tests prove a safer higher-throughput model.

Do not trade correctness for speculative throughput.

---

# 22. Phase 18 — Documentation truth audit

**Priority: P1**

Every document must distinguish:

```text
implemented
implemented but opt-in
experimental
deprecated
planned
live-verified
not live-verified
```

Audit:

- README
- architecture
- API compatibility
- clients
- configuration
- deployment
- live transport
- release status
- phase status documents
- extension documentation

Remove claims that a phase is production-active when only its code/tests exist.

### Exit gate

Documentation and runtime behavior agree.

---

# 23. Implementation order

Do **not** implement phases in numerical order if a lower phase depends on a higher-risk capability correction.

Recommended order:

```text
A. Freeze baseline
       ↓
B. Backend capability inventory
       ↓
C. Backend interface
       ↓
D. Fix files/images
       ↓
E. Fix model resolution
       ↓
F. Preserve thinking/options
       ↓
G. Tool parser + bounded recovery
       ↓
H. Schema semantic preservation
       ↓
I. Streaming/SSE
       ↓
J. Context management
       ↓
K. Retry/cancellation/session health
       ↓
L. Observability activation decision
       ↓
M. Packaging/extension/docs
       ↓
N. Full unit + integration suite
       ↓
O. Live Gemini tests
       ↓
P. Hermes/OpenCode/Codex matrix
       ↓
Q. Release gate
```

This order intentionally puts **capability preservation before additional agent features**.

---

# 24. Definition of done

GeminiAgentBridge is not release-ready until all of these are true:

### Architecture

- [ ] HTTP layer is backend-independent.
- [ ] Modern backend is primary.
- [ ] Legacy backend is explicitly deprecated/isolated.
- [ ] Capability registry exists.
- [ ] No important request field disappears silently.

### Gemini Web transport

- [ ] Current maintained client API is used correctly.
- [ ] Model resolution is deterministic.
- [ ] Images/files are preserved.
- [ ] Thinking/options are preserved or explicitly rejected.
- [ ] Streaming works.
- [ ] Client lifecycle is safe.
- [ ] Cancellation works.

### Tool protocol

- [ ] Malformed JSON is handled.
- [ ] Nested raw JSON parsing is robust.
- [ ] Tool schemas are enforced.
- [ ] Tool choice semantics are enforced.
- [ ] Multiple tool calls preserve order/IDs.
- [ ] Repair is bounded.
- [ ] Retry cannot duplicate tool execution.

### Context

- [ ] Long trajectories have explicit budgets.
- [ ] Critical state survives compaction.
- [ ] Tool outputs are handled predictably.
- [ ] No workspace state is fabricated.

### API

- [ ] Chat Completions compatibility matrix passes.
- [ ] Responses subset is documented/tested.
- [ ] `/v1/models` matches actual capabilities.
- [ ] SSE failure semantics are deterministic.

### Security

- [ ] Loopback default.
- [ ] Remote authentication required.
- [ ] SSRF protection tested.
- [ ] Request/image limits tested.
- [ ] Secret-safe logging verified.
- [ ] Client errors do not leak credentials or internal secrets.

### Testing

- [ ] Unit suite passes.
- [ ] Backend contract suite passes.
- [ ] HTTP integration suite passes.
- [ ] Live Gemini smoke tests pass.
- [ ] Hermes passes.
- [ ] OpenCode passes.
- [ ] Generic OpenAI client passes.
- [ ] Long agentic task passes.
- [ ] Malformed-tool-call regression passes.

### Documentation

- [ ] Runtime activation status is truthful.
- [ ] Model capability claims are truthful.
- [ ] Compatibility limitations are explicit.
- [ ] Clean-install instructions work.

---

# 25. Release gate

A release candidate must satisfy:

```text
1. Clean repository
        ↓
2. Full automated suite green
        ↓
3. Backend contract suite green
        ↓
4. HTTP/SSE integration green
        ↓
5. Live Gemini Web smoke test green
        ↓
6. Multimodal live test green
        ↓
7. Tool recovery live test green
        ↓
8. Hermes real repository task green
        ↓
9. OpenCode real repository task green
        ↓
10. No capability-loss findings open
        ↓
11. Security/documentation audit green
        ↓
12. Release candidate
```

A green unit suite alone is **not** a release gate.

---

# 26. Current next action

**Do not start Hermes again yet.**

First implement the capability-preservation foundation:

```text
1. Inventory every request field in original server.py/gemini.py/tools.py.
2. Inventory every field currently accepted by GeminiAgentBridge.
3. Inventory what the maintained Gemini Web client actually accepts.
4. Build the backend capability matrix.
5. Create the internal backend request contract.
6. Fix file/image forwarding.
7. Fix model resolution.
8. Fix thinking/extra-option forwarding.
9. Add contract tests for all of the above.
10. Re-run the full suite.
```

Only after these are complete should we return to the original real-world failure:

```text
Gemini malformed tool call
        ↓
GeminiAgentBridge recovery
        ↓
Hermes/OpenCode
        ↓
real repository coding task
```

That sequence gives us evidence that we fixed the underlying bridge architecture rather than merely masking one HTTP 500.
