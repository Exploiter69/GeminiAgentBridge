# GeminiAgentBridge — Project Roadmap

> **Status:** Active master plan
> **Project:** Gemini Web → GeminiAgentBridge → OpenAI-compatible API → Hermes/OpenCode
> **Primary goal:** Build a reliable, zero-monthly-cost agentic coding bridge in which Gemini Web supplies the model/reasoning and Hermes/OpenCode owns filesystem, terminal, Git, tests, and other tool execution.
>
> **Important:** This document is the execution contract for the project. We follow the phases in order. A phase is not considered complete because an agent says it is complete; completion requires independent verification and recorded evidence.

---

## 0. Non-Negotiable Architecture

```text
                         ┌──────────────────────────────┐
                         │          Gemini Web           │
                         │  reasoning / response source │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │      GeminiAgentBridge       │
                         │                              │
                         │  • transport                 │
                         │  • prompt/context building   │
                         │  • tool-call protocol        │
                         │  • schema validation         │
                         │  • repair/recovery           │
                         │  • grounding/observability   │
                         └──────────────┬───────────────┘
                                        │ OpenAI-compatible
                                        ▼
                         ┌──────────────────────────────┐
                         │       Hermes / OpenCode      │
                         │                              │
                         │  • Read / Search             │
                         │  • Edit / Write              │
                         │  • Bash / Terminal           │
                         │  • Git / Tests               │
                         │  • working-directory state   │
                         └──────────────────────────────┘
```

### Hard boundary

**GeminiAgentBridge must not execute downstream tools.**

The bridge may understand, parse, validate, repair, classify, and return tool calls. Hermes/OpenCode executes them and returns observations/results. The bridge must never become a second shell/filesystem agent.

### Source of truth for working directory

Hermes/OpenCode remains responsible for runtime working-directory state. The bridge may carry explicit grounding/context facts through prompts and traces, but it must not invent an independent filesystem state that competes with the downstream agent.

---

# 1. Current Baseline

## Completed

### Phase 1 — Strict tool protocol
- Strict sentinel tool-call parsing.
- Legacy fenced parsing compatibility.
- Fail-closed malformed candidates.
- `args` / `arguments` normalization.
- Stringified JSON normalization.
- Deterministic SHA-256 call IDs.
- Duplicate tool-call deduplication.
- Protocol tests.

### Phase 2 — Schema + bounded repair
- Strict tool protocol mode.
- Tool context isolation.
- Schema validation.
- Type / enum / required / properties / additionalProperties / arrays / items / minLength validation.
- Bounded repair loop.
- Repair prompt generation.
- Tool prompt monkeypatching.
- Gemini generation retry/repair integration.

### Phase 3 — Agent contract reliability
Commit baseline: `e73dd52`

Verified baseline: **41 tests passing**.

Covered:
- Multi-tool ordering and unique IDs.
- Duplicate-call deduplication.
- Malformed-call repair before client delivery.
- Bounded repair attempts.
- `/v1/chat/completions` OpenAI-compatible tool calls.
- `/v1/responses` tool-call/tool-result continuity.
- Tool messages preserved when tools are absent.
- Per-prompt tool-context reset.

### Benchmark lessons
- B3: production syntax corruption was successfully diagnosed and fixed.
- B4/B5: implementation can be correct while an agent falsely claims that a regression test was added. **Agent reports are not verification.**
- B6: a benchmark requiring the bridge to suppress tool side effects was architecturally invalid because tool execution belongs to Hermes/OpenCode.
- B7/F1: repository-grounding and reporting failures demonstrated that an agent can hallucinate files, classes, tests, and successful edits that do not exist. Every future agent task requires filesystem/git evidence.

### Current research status
Independent research and comparison of Gemini, Grok, Claude, Perplexity material plus direct source verification established that parser correctness alone is insufficient. The project must be treated as a **trajectory reliability system**.

---

# 2. Reliability Model

Every agent trajectory is evaluated as:

```text
USER INTENT
    ↓
CONTEXT / STATE CONSTRUCTION
    ↓
TOOL SELECTION
    ↓
ARGUMENT GENERATION
    ↓
ARGUMENT VALIDATION
    ↓
TOOL CALL RETURNED TO AGENT
    ↓
DOWNSTREAM EXECUTION (Hermes/OpenCode)
    ↓
OBSERVATION / TOOL RESULT
    ↓
OBSERVATION INTEGRITY
    ↓
NEXT ACTION
    ↓
FINAL STATE / ANSWER
```

The bridge owns the protocol boundary, not execution.

The major reliability dimensions are:

1. Protocol correctness
2. Schema correctness
3. Tool-selection correctness
4. Argument correctness
5. Workspace/working-directory grounding
6. Observation integrity
7. Context-budget management
8. Multi-turn continuity
9. Recovery behavior
10. Long-horizon trajectory reliability
11. Compatibility with Hermes/OpenCode
12. Honest observability/reporting

---

# 3. Phase Gates

Every phase follows this exact loop:

```text
1. Inspect current repository state
2. Create isolated/disposable test environment when appropriate
3. Establish baseline
4. Define one measurable hypothesis
5. Implement the smallest change
6. Add regression tests
7. Run focused tests
8. Run full suite
9. Inspect git diff/status
10. Re-run independently where possible
11. Record PASS / FAIL / INVALID
12. Only then advance
```

### Required reporting format

```text
PHASE: <name>
STATUS: PASS | FAIL | INVALID | BLOCKED
BASELINE: <test/result>
CHANGES: <files + purpose>
FOCUSED TESTS: <exact command + result>
FULL SUITE: <exact command + result>
INDEPENDENT VERIFICATION: <exact evidence>
REMAINING RISKS: <list>
COMMIT: <sha or N/A>
```

**No fabricated test counts, files, commits, fixes, or claims of success.**

---

# 4. Phase 4A — Restore Own Runtime + Diagnostic Instrumentation

**Priority: P0**

## Goal

Return Hermes to the user's own GeminiAgentBridge instance on **localhost:8081**, while keeping temporary fork testing isolated on other ports. Then establish complete request/response/tool-call visibility without exposing credentials.

## Runtime topology

```text
8081 = user's own GeminiAgentBridge / own Gemini Web account/session
8082 = temporary mcfax test instance (only for controlled comparison)
```

Do not mix these configurations.

## Tasks

- Restore Hermes `model.base_url` to `http://127.0.0.1:8081/v1`.
- Verify `/v1/models` on 8081.
- Verify the 8081 process working directory is the user's own bridge repository.
- Verify the 8081 server is using the user's existing local account/session configuration without printing secrets.
- Keep mcfax on 8082 for comparison until its Hermes behavior is fully diagnosed.
- Add safe trace IDs and request lifecycle logging if not already present.
- Never log cookies, API hashes, session contents, authorization headers, or credential values.

## Acceptance

- Hermes points to 8081.
- 8081 is proven to be the user's bridge process.
- 8082 remains isolated.
- No credential material appears in logs/tests.
- Baseline suite remains green.

---

# 5. Phase 4B — Reproduce and Solve the Wrong-Path / Context Problem

**Priority: P0 / blocking**

This is the central engineering problem discovered during the mcfax → Hermes test.

## Known incident

Hermes was asked to inspect `/tmp/hermes-mcfax-test`, list files, and read `sample.txt`.

Expected fixture:

```text
README.md
sample.txt

sample.txt:
alpha
beta
gamma
```

Observed answer referenced an unrelated path under the user's home directory and claimed the file was empty.

This proves that the agent trajectory was not grounded in the requested workspace. It does **not** yet prove which layer caused the failure.

## Hypotheses to test, in order

1. Hermes launch-directory / `--in` propagation.
2. Hermes runtime CWD state.
3. Tool schema/path representation.
4. Model prior or hallucinated filename/path.
5. Bridge prompt/context construction.
6. Bridge tool-call parsing or argument transformation.
7. Tool-result formatting/loss.
8. Context truncation or state loss.
9. mcfax-specific planner behavior.
10. Session/memory contamination.

## Required controlled experiments

### A. Direct filesystem control
Run the exact fixture and verify it independently with shell commands.

### B. Hermes without bridge comparison
Test Hermes with its normal known-good model/provider if available, using the same directory and task.

### C. Hermes → mcfax 8082
Capture the exact outbound request and exact returned tool call.

### D. Hermes → user's bridge 8081
Repeat the identical task and capture the exact returned tool call.

### E. Direct API test
Send the same OpenAI-compatible request directly to 8081 with `curl` and inspect the returned tool call. This separates Hermes behavior from bridge behavior.

### F. Fresh Hermes state
Repeat with a clean/fresh Hermes session/profile where practical. Do not assume memory contamination without evidence.

### G. CWD ablation
Compare:
- launch directory
- explicit `--in`
- explicit Hermes `terminal.cwd`
- tool argument containing absolute path
- tool argument containing relative path

## Required evidence

For each experiment record:

```text
requested cwd
Hermes launch cwd
bridge request cwd facts
returned tool name
returned tool arguments
simulated/executed tool result
next model response
final reported path
```

## Acceptance

The root cause is identified to a specific layer or narrowed to a small set of reproducible causes.

A regression test reproduces the original failure before the fix and passes after the fix.

No solution may silently hard-code the user's current directory.

---

# 6. Phase 4C — Grounding Contract

**Priority: P0**

## Goal

Make workspace identity and task state explicit enough that prompt-emulated tool calling does not drift into unrelated files or paths.

## Design

Introduce a structured internal grounding contract, conceptually:

```python
GroundingFacts(
    requested_cwd=...,
    runtime_cwd=...,
    task_target=...,
    known_files=...,
    open_files=...,
    last_tool_call=...,
    last_tool_result=...,
)
```

The exact implementation may differ after repository inspection.

## Rules

- Never invent filesystem facts.
- Never claim a tool executed when the bridge did not execute it.
- Never fabricate tool results.
- Prefer explicit facts over inferred paths.
- Preserve recent tool call/result pairs.
- Keep Hermes/OpenCode as the execution-state owner.
- Bridge may validate consistency and surface uncertainty.
- Ambiguous grounding should trigger repair/recovery rather than confident fabrication.

## Acceptance

Tests cover:
- correct absolute path
- correct relative path
- wrong path proposed by model
- missing path
- multiple candidate files
- tool result referencing a path
- path continuity across multiple turns

---

# 7. Phase 4D — Context Budget and Observation Management

**Priority: P0**

## Goal

Prevent long agent trajectories from losing critical state while keeping prompts within practical Gemini Web limits.

## Rules

The bridge must distinguish:

```text
SYSTEM / CONTRACT
TASK / USER INTENT
CURRENT STATE
RECENT TOOL CALLS
RECENT TOOL RESULTS
OLDER HISTORY
ELIDED HISTORY
```

Preservation priority:

1. system/contract
2. current task
3. current grounding facts
4. latest tool call
5. latest tool result
6. recent tool/result pairs
7. compact summary of older state
8. least-important old history

## Tool-result policy

Large tool results must be bounded without destroying the information needed for the next action.

Potential strategy:

```text
small result → preserve fully
large result → structured head/tail + metadata
very large result → compact summary + retrieval hint
```

Do not blindly adopt a fixed percentage split. Measure task performance.

## Prompt-budget policy

Do not claim an exact Gemini Web hard limit unless experimentally verified for the active transport/session.

Use:
- configurable soft budget
- measured request size
- safe margin
- deterministic truncation
- explicit elision markers

## Acceptance

Tests demonstrate that:
- recent tool state survives truncation
- old irrelevant history can be removed
- task identity survives compaction
- CWD/grounding facts survive compaction
- tool results are never silently fabricated
- oversized results do not break the protocol

---

# 8. Phase 5 — Recovery and Error Semantics

**Priority: P1**

## Goal

Recover from common Gemini Web failures without causing hidden state corruption.

## Implement/test

- upstream timeout classification
- retry with bounded attempts
- rate/usage-limit classification
- authentication/session failure classification
- empty response detection
- malformed tool-call recovery
- invalid schema recovery
- missing required argument recovery
- empty tool-result recovery
- explicit failed-observation handling

## Important rule

A failed tool result is data. It must not be rewritten as a successful result.

Example:

```text
TOOL RESULT:
status = error
error_type = file_not_found
path = /requested/path
```

is fundamentally different from:

```text
TOOL RESULT:
files = []
```

unless the downstream tool actually returned an empty result.

## Acceptance

Every recovery path has:
- bounded retries
- deterministic tests
- no fabricated observation
- no infinite loop
- clear client-visible error when recovery fails

---

# 9. Phase 6 — Tool-Choice Reliability

**Priority: P1**

## Goal

Improve the reliability of prompt-emulated function calling.

## Required cases

- `tool_choice=none`
- automatic tool selection
- required tool use where client requests it
- multiple tools
- ordered multi-tool calls
- duplicate calls
- malformed JSON
- wrong tool name
- missing required argument
- enum mismatch
- extra property
- arguments supplied as string JSON
- empty arguments

## Policy

The bridge may repair formatting/schema errors but must not manufacture arbitrary tool intent.

---

# 10. Phase 7 — Planner Experiment (Optional / Feature Flag)

**Priority: P1/P2**

The deterministic planner ideas from mcfax are valuable but risky.

## Default state

Planner **OFF** until grounding and trajectory benchmarks are green.

## Confidence tiers

```text
HIGH confidence
    → planner may synthesize a tool call

MEDIUM confidence
    → ask Gemini to repair/clarify

LOW confidence
    → do not synthesize a tool call
```

## Never do

- arbitrary guessed tool calls
- guessed filesystem paths
- silent execution
- planner calls without evidence
- planner overriding explicit model intent without a safety reason

## Experiments

Measure planner on:
- obvious search/list requests
- obvious read requests
- obvious edit requests
- ambiguous requests
- multi-step requests
- wrong-path requests

Planner must be evaluated against Gemini-only baseline.

---

# 11. Phase 8 — Hermes / OpenCode Compatibility

**Priority: P1**

## Goal

Prove that the bridge works with real agent clients, not only synthetic HTTP tests.

## Hermes

Test:
- list files
- read file
- create file
- edit file
- terminal command
- search then read
- search then edit
- multi-step task
- test execution
- Git status
- Git diff
- explicit working directory
- long task

## OpenCode

Repeat the same core matrix where supported.

## Acceptance

Client-visible behavior is correct across the matrix. A passing `/v1/chat/completions` unit test alone is insufficient.

---

# 12. Phase 9 — Trajectory Reliability Benchmark

**Priority: P0/P1**

The benchmark becomes a permanent regression suite.

## Dimensions

| Dimension | What it measures |
|---|---|
| Protocol | Parser/format correctness |
| Schema | Arguments satisfy tool schema |
| Selection | Correct tool chosen |
| Grounding | Correct workspace/path/file |
| Observation | Tool result preserved correctly |
| Continuity | State survives turns |
| Recovery | Errors recover safely |
| Context | Important state survives compaction |
| Horizon | Multi-step reliability |
| Client | Hermes/OpenCode compatibility |

## Metrics

Record at minimum:

- Pass@1
- Pass@3
- Pass^3
- Pass^5

Where useful, also record Pass@k for larger k.

### Meaning

- **Pass@1:** probability that one attempt succeeds.
- **Pass@k:** whether at least one of k attempts succeeds.
- **Pass^k:** probability that all k repeated attempts succeed.

Pass^k is particularly important for agentic coding because inconsistent trajectories are a real failure mode.

## Benchmark tasks

### Read-only

1. List exact directory.
2. Read exact file.
3. Search for known string.
4. Read multiple files.
5. Report exact contents.

### Mutating

6. Create exact file.
7. Edit exact file.
8. Apply small code change.
9. Run tests.
10. Inspect Git diff.

### Multi-step

11. Search → read → edit → test.
12. Find failing code → patch → test.
13. Inspect project → identify file → modify → verify.

### Adversarial grounding

14. Same filename exists elsewhere.
15. Similar project exists elsewhere.
16. Wrong path appears in model prior.
17. Tool result contains misleading text.
18. Old context mentions another repository.
19. Long history with multiple directories.
20. Context compaction before the critical tool call.

---

# 13. Phase 10 — Observability and Auditability

**Priority: P1**

## Goal

Make every failure explainable.

## Trace model

Each request receives a non-secret trace ID.

Conceptual events:

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
final_response
error
```

## Privacy rules

Never record:
- cookies
- session files
- API hashes
- bearer tokens
- authorization headers
- personal account secrets

Record metadata instead.

## Acceptance

A failed trajectory can be reconstructed from safe logs without exposing credentials.

---

# 14. Phase 11 — Selective Feature Porting from Other Projects

Only port features after proving the need in our benchmark.

## KEEP

From current project:
- strict parser
- fail-closed malformed handling
- schema validation
- bounded repair
- deterministic IDs
- deduplication
- OpenAI-compatible responses
- Responses API continuity

## ADAPT

From Boris-style infrastructure:
- prompt-size management
- tool-result truncation
- upstream error classification
- account/session lifecycle ideas only if needed later
- compatibility improvements required by real clients

## SELECTIVELY IMPORT

From mcfax:
- compact tool definitions
- safe enum coercion
- tool-result recovery concepts
- deterministic planner only behind a feature flag and only after grounding benchmarks

## INVESTIGATE

- additional streaming behavior
- multi-account routing
- prompt-size empirical limits
- alternative protocol formats

## REJECT FOR NOW

- bridge-side tool execution
- fabricated tool results
- unrestricted deterministic planner
- blind adoption of an alleged fixed Gemini Web byte/token limit
- multi-account rotation before single-account reliability is proven

---

# 15. Phase 12 — Performance / Stability

After correctness is stable:

- reduce unnecessary upstream requests
- tune retry delays
- reduce prompt bloat
- optimize parser cost
- optimize context compaction
- test concurrent requests
- test long sessions
- test repeated sessions
- test idle/reconnect behavior

Correctness always wins over latency optimization.

---

# 16. Phase 13 — Release Candidate / Go-No-Go

The project is release-ready only when all of these are true:

### Architecture
- [ ] Gemini Web remains the model/reasoning source.
- [ ] Bridge remains transport/protocol/reliability layer.
- [ ] Hermes/OpenCode remain tool executors.
- [ ] No hidden bridge-side filesystem/shell execution.

### Protocol
- [ ] Existing Phase 1–3 tests remain green.
- [ ] Malformed calls fail safely.
- [ ] Schema errors are deterministic.
- [ ] Tool IDs are stable/deduplicated.
- [ ] Chat Completions compatibility works.
- [ ] Responses compatibility works.

### Grounding
- [ ] CWD behavior is deterministic.
- [ ] Wrong-path regression is fixed.
- [ ] Similar-path/file confusion is tested.
- [ ] Context compaction preserves workspace identity.

### Observation integrity
- [ ] No fabricated tool results.
- [ ] Errors remain errors.
- [ ] Empty results remain distinguishable from failures.

### Context
- [ ] Prompt budget is configurable.
- [ ] Tool results are bounded safely.
- [ ] Critical recent state survives compaction.

### Agent clients
- [ ] Hermes core workflow passes.
- [ ] OpenCode core workflow passes.

### Trajectory
- [ ] Baseline benchmark recorded.
- [ ] Pass@1 measured.
- [ ] Pass@3 measured.
- [ ] Pass^3 measured.
- [ ] Pass^5 measured.
- [ ] No critical regression against baseline.

### Honesty
- [ ] Every reported test has reproducible evidence.
- [ ] Every claimed file exists.
- [ ] Every claimed change appears in `git diff`.
- [ ] Every claimed commit exists.
- [ ] No agent is trusted as its own verifier.

---

# 17. Rollback Policy

Every behavior-changing phase must have a rollback point.

Before modifying production behavior:

```bash
git status --short
git log -1 --oneline
python -m unittest discover -s tests -p 'test_*.py' -v
```

If a phase fails:

1. Preserve diagnostic evidence.
2. Do not stack speculative fixes.
3. Revert only the failed experiment where practical.
4. Restore green baseline.
5. Add a regression test for the discovered failure.
6. Re-evaluate the hypothesis.

Never hide a failed experiment by deleting evidence.

---

# 18. Working Rules for This Chat

This roadmap is the persistent project memory for the engineering work.

When continuing this project in a future conversation:

1. Start by reading `roadmap.md`.
2. Identify the current phase and gate.
3. Do not skip unfinished earlier phases.
4. Do not repeat completed phases unless a regression requires it.
5. Do not modify code before establishing the current baseline when the phase requires it.
6. Prefer small, independently verifiable changes.
7. Use disposable worktrees/directories for risky experiments.
8. Keep the user's own 8081 environment distinct from temporary forks such as 8082.
9. Never expose credentials, cookies, session data, or secrets.
10. If an agent claims success, independently inspect `git status`, `git diff`, files, and tests.
11. Record phase completion in this file when appropriate.
12. Do not advance merely because a test passes; the test must cover the actual failure mode.

---

# 19. Current Execution Queue

## NOW — Phase 4A

- [ ] Restore Hermes endpoint to user's own bridge: `http://127.0.0.1:8081/v1`.
- [ ] Verify 8081 is the user's own bridge process/repository.
- [ ] Verify 8081 `/v1/models`.
- [ ] Keep 8082 isolated as the temporary mcfax comparison server.
- [ ] Establish safe diagnostic logging/tracing.
- [ ] Run the original wrong-path reproduction against 8081.

## NEXT — Phase 4B

- [ ] Capture exact Hermes → bridge request.
- [ ] Capture exact bridge → Hermes tool-call response.
- [ ] Capture actual downstream tool result.
- [ ] Compare 8081 vs 8082.
- [ ] Compare Hermes behavior with direct API behavior.
- [ ] Identify the failing layer.
- [ ] Add a regression test before implementing the fix.

## THEN

- [ ] Phase 4C grounding contract.
- [ ] Phase 4D context/observation budget.
- [ ] Phase 5 recovery.
- [ ] Phase 6 tool-choice reliability.
- [ ] Phase 7 planner experiment.
- [ ] Phase 8 Hermes/OpenCode compatibility.
- [ ] Phase 9 trajectory benchmark.
- [ ] Phase 10 observability.
- [ ] Phase 11 selective feature porting.
- [ ] Phase 12 performance/stability.
- [ ] Phase 13 release candidate.

---

# 20. Final Definition of Success

The project is successful when the user can point Hermes or OpenCode at a real coding repository and say, for example:

> "Inspect this project, find the bug, fix it, run the tests, and show me the diff."

and the system reliably performs:

```text
Gemini Web
   ↓
understands task
   ↓
GeminiAgentBridge
   ↓
produces validated, grounded tool calls
   ↓
Hermes/OpenCode
   ↓
actually reads/edits/runs/tests
   ↓
returns real observations
   ↓
Gemini Web
   ↓
chooses next action
   ↓
Hermes/OpenCode
   ↓
verified final state
```

The objective is **not** merely to make Gemini output valid JSON.

The objective is **reliable multi-step coding behavior with truthful state, grounded tool calls, bounded context, recoverable failures, and independently measurable trajectory reliability.**
