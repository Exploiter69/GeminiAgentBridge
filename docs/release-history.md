# Release and phase history

This is a concise historical index. Detailed implementation rationale remains in `roadmap.md` and the phase-specific evidence files.

| Phase | Status | Main result |
|---|---|---|
| 1 | Complete | strict tool protocol and parser hardening |
| 2 | Complete | schema validation and bounded repair |
| 3 | Complete | agent contract and tool-result continuity |
| 4 | Complete | runtime reliability, grounding, context, and direct integration work |
| 5 | Complete | recovery and error semantics |
| 6 | Complete | tool-choice reliability |
| 7 | Complete / conservative | deterministic planner experiment, disabled by default |
| 8 | Complete | Hermes/OpenCode compatibility contract and local real-client evidence |
| 9 | Complete | trajectory reliability benchmark |
| 10 | Complete | structured observability and auditability |
| 11 | Complete | selective feature ports with conservative boundaries |
| 12 | Complete | performance/stability and bounded retry improvements |
| 13 | Complete | independent release-candidate verification |
| Live transport repair | In progress | replace stale default Gemini Web transport with maintained `gemini-webapi` path |

## Phase 8 evidence

The durable local real-client gate recorded:

- Hermes: 13/13;
- OpenCode: 13/13;
- combined: 26/26.

This is historical evidence from the pre-repair transport state.

## Phase 9 evidence

The trajectory benchmark recorded 22 cases across 5 attempts with all tracked dimensions at 1.0 in the verified run.

## Phase 12 verification

The final Phase 12 gate recorded:

- Python 3.11/3.14 green;
- 155 full tests passing;
- compileall passing;
- diff check passing;
- deterministic performance benchmark passing;
- Phase 11/9/8 regressions passing;
- credential-pattern scan passing.

## Phase 13

Phase 13 added an independent repository-level release verifier, machine-readable evidence, a SHA-256 manifest, and a durable release-status record. It intentionally did not treat agent claims as verification.

## Live transport repair

Real Hermes testing subsequently exposed the old direct `StreamGenerate` path returning HTTP 405/429 behavior. The repair branch introduces the maintained Gemini Web client as the default package transport while keeping the legacy path explicit.

The repair is not marked released until a fresh authenticated live upstream gate and real-client regression pass.
