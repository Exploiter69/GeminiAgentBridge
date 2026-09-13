# Phase 13 Release Candidate Status

This document is the durable release-status record for the Phase 13 gate.

## Scope

Phases 1–12 are complete and independently verified through their phase regressions and CI history. Phase 13 adds an independent repository-level release verifier rather than relying on agent-reported success.

## Honesty / auditability gate

- Reproducible regression commands are executed by `scripts/phase13_release_candidate.py`.
- Required files are checked from the repository filesystem.
- Historical phase commits are resolved with Git and checked as ancestors of the release candidate.
- Phase 13 changed paths are verified against the Phase 12 baseline.
- Compile, credential-pattern, full-suite, trajectory, and performance gates are executed independently.
- Real Hermes/OpenCode evidence is preserved separately in `docs/phase8-real-client-evidence.md` because hosted CI does not provide those installed clients.
- The verifier records `agent_claims_used_as_verification: false`.
- Machine-readable evidence and a SHA-256 manifest are emitted under `artifacts/` by the release gate.

## Release rule

`GO` requires every deterministic check to pass and the durable Hermes/OpenCode evidence to exist and contain the required 13/13 + 13/13 result. No agent response is accepted as proof.

## Roadmap execution-state correction

The older Phase 4–12 execution queue in `roadmap.md` is historical/stale relative to the merged repository state. Phase 13 is the active release gate; this status document is the explicit durable release-state record until the roadmap's queue is rewritten in a future documentation-only update.
