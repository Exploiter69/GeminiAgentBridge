# Phase 8 Real-Client Evidence

This is a durable record of the independent local Hermes/OpenCode gate executed before Phase 13.

## Command

```bash
python scripts/phase8_client_compat.py --hermes --opencode
```

## Result

- Hermes: **13/13 cases passed**
- OpenCode: **13/13 cases passed**
- Combined: **26/26 cases passed**
- Required matrix: 13/13 roadmap cases
- Bridge execution boundary remained intact; downstream filesystem/terminal execution stayed with the agent clients.

The execution was performed as a local real-client gate because GitHub-hosted CI does not provide the user's installed Hermes/OpenCode environments. The harness itself is committed at `scripts/phase8_client_compat.py` and creates isolated temporary workspaces for each case.

This document is evidence of that prior independent run, not a claim that the hosted CI runner executed Hermes/OpenCode.
