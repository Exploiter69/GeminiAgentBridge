# Phase 13 Release Candidate Status

Phase 13 is the durable record of the repository-level release gate performed
before promotion of the repaired Gemini Web transport.

## Historical evidence

An earlier Phase 13 run produced a historical `GO` for the then-current codebase
and was merged at:

```text
a6e9e72bfe09a35974a456779ac8afeaad775477
```

That result is retained as regression evidence only. It is **not** a release
certificate for the current transport repair.

## Current release gate

The current candidate must prove all of the following again:

- backend capability and health lifecycle contracts are deterministic;
- unsupported semantics are explicit and token usage is never fabricated;
- streaming failures after HTTP commitment produce an explicit error event and no
  false `[DONE]` success marker;
- Responses compatibility does not invent unavailable provider metadata;
- legacy transport remains available only behind an explicit compatibility boundary;
- package/module/entry-point compatibility is tested;
- session-extension behavior is credential-safe and local-only;
- long-trajectory and performance regression suites remain green;
- a **fresh authenticated Gemini Web** non-streaming and streaming run succeeds;
- **fresh Hermes and OpenCode agent runs** succeed against the repaired branch;
- the independent Phase 13 verifier returns `GO` only after the fresh evidence is
  recorded.

Fresh evidence is maintained in [`docs/fresh-live-evidence.md`](fresh-live-evidence.md)
without storing any credential material.

Until those conditions are met, the repair branch remains unreleased and must not
be merged.
