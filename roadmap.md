# GeminiAgentBridge roadmap

> **Current status:** transport repair in progress
>
> **Goal:** provide a reliable, zero-monthly-cost Gemini Web reasoning backend through an OpenAI-compatible local API while Hermes/OpenCode remain responsible for filesystem, terminal, Git, tests, and other downstream tool execution.

## Architecture contract

```text
Gemini Web
   │ reasoning / model response
   ▼
GeminiAgentBridge
   │ protocol + context + validation + recovery + observability
   ▼
Hermes / OpenCode
   │ tool execution + workspace state
   ▼
local files / shell / Git / tests
```

### Hard boundaries

- The bridge does not execute downstream tools.
- Hermes/OpenCode owns the real working directory and tool observations.
- The bridge must not invent filesystem facts or tool results.
- Credentials and session material never belong in tests, logs, commits, or documentation.
- A model response is not proof that a tool executed.

## Completed phases

| Phase | Status | Result |
|---|---|---|
| 1 | PASS | strict tool protocol and parser hardening |
| 2 | PASS | schema validation and bounded repair |
| 3 | PASS | agent contract and tool/result continuity |
| 4 | PASS | grounding, context, runtime reliability, recovery foundations |
| 5 | PASS | bounded recovery and error semantics |
| 6 | PASS | tool-choice reliability |
| 7 | PASS / conservative | planner experiment; disabled by default |
| 8 | PASS | Hermes/OpenCode compatibility contract and local real-client gate |
| 9 | PASS | trajectory reliability benchmark |
| 10 | PASS | structured observability and auditability |
| 11 | PASS | selective conservative feature ports |
| 12 | PASS | performance/stability and bounded retries |
| 13 | PASS / historical | independent release-candidate verification |

## Verified evidence

### Phase 8

The independent local real-client gate recorded:

- Hermes: **13/13**;
- OpenCode: **13/13**;
- combined: **26/26**.

Hosted CI does not provide the user's installed real clients, so this remains explicitly local evidence.

### Phase 9

The trajectory benchmark recorded 22 cases across 5 attempts with all tracked dimensions at 1.0 in the verified run.

### Phase 12

The final verification recorded:

- Python 3.11/3.14 green;
- 155 full tests passing;
- compileall passing;
- diff check passing;
- deterministic performance benchmark passing;
- Phase 11/9/8 regressions passing;
- credential-pattern scan passing.

### Phase 13

The independent release verifier produced a `GO` for the then-current repository state, including the historical real-client evidence. It intentionally did not use agent claims as verification.

## Current work — Live Gemini Web transport repair

Real Hermes testing exposed a critical distinction between the historical top-level server and the maintained package server. The old direct Gemini Web `StreamGenerate` path could produce HTTP 405/429 behavior against current Gemini Web. The repair branch therefore introduces a maintained `gemini-webapi==2.1.1` transport as the package default while retaining the legacy implementation only as an explicit compatibility backend.

### Completed in the repair branch

- persistent modern `GeminiClient` lifecycle;
- background asyncio event loop for synchronous bridge handlers;
- local session/cookie file support;
- bounded retries and client reset for auth/session/model failures;
- conservative model-tier mapping;
- modern transport unit tests without credentials;
- package entrypoint documentation;
- explicit legacy-vs-modern troubleshooting guidance.

### Still required before release

1. fresh authenticated Gemini Web non-streaming generation;
2. fresh authenticated Gemini Web streaming generation;
3. real Hermes smoke test against the repaired transport;
4. real OpenCode smoke test where installed;
5. fix/verify partial-stream error propagation;
6. rerun the complete deterministic release gate;
7. update release status only from actual observed evidence;
8. merge the transport repair only after the above passes.

## Phase gate policy

Every phase follows:

```text
inspect → baseline → hypothesis → smallest change → regression tests
→ focused tests → full suite → diff/status → independent verification
→ recorded PASS/FAIL/BLOCKED → next phase
```

Required evidence format:

```text
PHASE: <name>
STATUS: PASS | FAIL | BLOCKED | INVALID
BASELINE: <result>
CHANGES: <files + purpose>
FOCUSED TESTS: <command + result>
FULL SUITE: <command + result>
INDEPENDENT VERIFICATION: <evidence>
REMAINING RISKS: <list>
COMMIT: <sha>
```

## Future work after transport release

Only after the live transport is stable:

- expand real-client matrices;
- improve streaming failure semantics;
- add more deterministic long-horizon trajectories;
- keep context compaction measurable rather than hard-coded;
- revisit planner behavior only with evidence;
- track Gemini Web protocol changes without coupling the bridge to stale private endpoints.

## Documentation rule

This roadmap describes the current repository state. Historical claims remain labeled as historical. A merged phase is not evidence that a later transport change is also healthy.
