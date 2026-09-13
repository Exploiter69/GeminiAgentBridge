# Phase 13 Release Candidate Status

Phase 13 is the durable record of the independent repository-level release gate performed before the current live Gemini Web transport repair.

## What Phase 13 proved

- repository/git integrity checks passed;
- historical phase commits were checked as ancestors of the candidate;
- compile, credential-pattern, full-suite, trajectory, and performance gates were executed independently;
- the durable Hermes/OpenCode real-client evidence existed and contained the required 13/13 + 13/13 result;
- machine-readable release evidence and a SHA-256 manifest were emitted under `artifacts/`;
- the verifier recorded `agent_claims_used_as_verification: false`.

## Historical result

Phase 13 produced a `GO` for the codebase that existed at that point and was merged at:

```text
a6e9e72bfe09a35974a456779ac8afeaad775477
```

## Important status correction

The subsequent live-client investigation found that the old default execution path could still reach the historical direct `StreamGenerate` implementation and produce HTTP 405/429 behavior. The current repair branch therefore changes the live upstream transport.

That means the Phase 13 `GO` is **historical evidence**, not a release certificate for the changed transport.

## Current release gate

The current transport repair must establish all of the following again:

- maintained modern Gemini Web transport is the actual live path;
- a fresh authenticated Gemini Web session can generate non-streaming output;
- the same session can generate streaming output;
- Hermes can use the resulting server for real agent work;
- OpenCode can use the resulting server where installed;
- streaming failures are not misreported as successful completions;
- deterministic regression and credential-safety gates remain green.

Until those conditions are met, the repair branch remains unreleased.
