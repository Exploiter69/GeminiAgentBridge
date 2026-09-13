# Release status

## Current branch

`repair-live-gemini-web`

Current repair head at the start of this documentation refresh:

```text
faa27860d0d0627221b872a75e151631b6ca4651
```

The live-transport repair is represented by open draft PR #12 and is intentionally not considered merged/released until its live upstream gate passes.

## Last released/merged baseline

Phase 13 was merged at:

```text
a6e9e72bfe09a35974a456779ac8afeaad775477
```

That release-candidate gate recorded a deterministic `GO` for the then-current codebase, including the historical Hermes/OpenCode evidence.

## Why the current branch is not automatically released

The repair changes the live Gemini Web transport. Historical tests prove the bridge's protocol and agent-client behavior, but they do not prove that the newly selected upstream transport can authenticate and generate against today's Gemini Web session.

The current evidence has established:

- modern package entrypoint is selected;
- `gemini-webapi==2.1.1` is installed in the project virtual environment;
- modern transport can initialize against a supplied session file;
- the tested session was reported as `UNAUTHENTICATED` by the upstream client;
- therefore a fresh authenticated generation pass is still required.

## Go/no-go criteria for the transport repair

### Required

- [x] deterministic transport tests;
- [x] full repository regression suite before the live repair;
- [x] compile/diff checks before the live repair;
- [x] legacy path isolated as explicit compatibility behavior;
- [x] modern path selected by default;
- [ ] fresh authenticated non-streaming Gemini Web generation;
- [ ] fresh authenticated streaming Gemini Web generation;
- [ ] real Hermes smoke test against the repaired transport;
- [ ] real OpenCode smoke test where installed;
- [ ] streaming error propagation reviewed after live generation is proven;
- [ ] final release-candidate gate rerun after the transport changes.

## Evidence policy

Historical evidence remains useful but cannot be reused as proof for a changed transport. Every release candidate must state exactly which commands ran and which results were observed.
