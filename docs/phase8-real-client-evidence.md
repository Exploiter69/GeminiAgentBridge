# Phase 8 Real-Client Evidence

This document records the independent local Hermes/OpenCode compatibility gate executed before the current live Gemini Web transport repair.

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

The harness creates isolated temporary workspaces and does not require hosted CI to provide the user's installed agent clients.

## Evidence boundary

This is **historical real-client evidence** for the transport/client contract that existed before the current Gemini Web upstream repair. It is not a claim that GitHub-hosted CI executed Hermes/OpenCode, and it is not a claim that the current unreleased `repair-live-gemini-web` transport has passed a fresh live Gemini Web generation test.

A changed upstream transport requires a new live gate before the historical 26/26 result can be cited as release evidence for that transport.
