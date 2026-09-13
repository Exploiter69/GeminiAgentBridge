# Architecture

## Purpose

`gemini-web2api` is a protocol and transport bridge. It exposes a local OpenAI-compatible API while Gemini Web remains the model/reasoning source and the downstream agent remains the execution owner.

## Ownership model

```text
┌──────────────────── Gemini Web ────────────────────┐
│ reasoning, model response, native web capabilities │
└─────────────────────────┬──────────────────────────┘
                          │
                 maintained web transport
                          │
                          ▼
┌────────────────── GeminiAgentBridge ──────────────────┐
│ HTTP protocol                                          │
│ request normalization                                  │
│ prompt/context construction                             │
│ grounding facts                                        │
│ tool-call parsing + schema validation                  │
│ bounded repair/recovery                                │
│ retry/error classification                              │
│ observability                                          │
└─────────────────────────┬──────────────────────────────┘
                          │ OpenAI-compatible response
                          ▼
┌──────────────── Hermes / OpenCode ────────────────────┐
│ tool selection/execution                               │
│ filesystem                                             │
│ terminal                                               │
│ Git                                                    │
│ tests                                                  │
│ working-directory state                                │
└────────────────────────────────────────────────────────┘
```

### Non-negotiable boundary

The bridge **does not execute downstream tools**. A tool call can be parsed, normalized, validated, repaired, and returned to Hermes/OpenCode, but the bridge never runs shell commands, reads arbitrary workspace files, edits repositories, or fabricates a tool result.

## Package entrypoint

The maintained package entrypoint is:

```bash
python -m gemini_web2api
```

The installed console entrypoint is:

```bash
gemini-web2api
```

The historical top-level `gemini_web2api.py` remains in the repository for compatibility. It contains the legacy direct Gemini Web implementation and should not be confused with the package server.

## Transport selection

`gemini_web2api/gemini.py` selects the upstream backend:

```text
upstream_backend != "legacy"
        │
        ▼
modern Gemini Web backend
        │
        └── gemini-webapi / GeminiClient

upstream_backend == "legacy"
        │
        ▼
legacy StreamGenerate implementation
```

The package default is `modern`. The legacy backend exists only as an explicit compatibility escape hatch.

## Modern transport lifecycle

`gemini_web2api/modern.py` maintains one long-lived `GeminiClient` behind a dedicated background asyncio event loop. Synchronous bridge handlers submit coroutines to that loop and wait for bounded completion.

The lifecycle is intentionally persistent because repeatedly creating a new upstream client for every request can lose session state and adds unnecessary initialization overhead.

On authentication/session/model-class failures the backend can close and reinitialize the client before a bounded retry. Credentials are never logged.

## Authentication layers

There are two unrelated credentials boundaries:

### Bridge authentication

`api_keys` protects the local HTTP API. It is an application-level credential chosen by the operator.

### Gemini Web authentication

`cookie_file` points to locally stored Gemini Web session material consumed by the maintained upstream client. The bridge reads it locally and never logs its contents.

A successful bridge authentication check says nothing about Gemini Web session validity.

## Context and grounding

The bridge constructs a model prompt from the incoming OpenAI-style conversation and protocol metadata. It can preserve explicit grounding facts such as requested working directory and recent tool/result continuity.

It must not invent filesystem state. Hermes/OpenCode remains authoritative for the actual workspace and tool observations.

## Tool-call lifecycle

```text
model response
   ↓
parse candidate tool calls
   ↓
normalize args / arguments
   ↓
validate against declared schema
   ↓
bounded repair if the error is deterministic and repairable
   ↓
return tool call to client
   ↓
client executes tool
   ↓
client returns observation
   ↓
bridge preserves observation integrity
```

Malformed data may be repaired. Missing real-world facts may not be invented.

## Observability

Phase 10 instrumentation emits structured lifecycle events with non-secret trace IDs. Recursive redaction prevents credential-like values from entering logs. Observability describes what the bridge observed; it does not claim downstream execution that the bridge did not perform.

## Reliability layers

The project evaluates trajectories across:

1. protocol correctness;
2. schema correctness;
3. tool selection;
4. argument correctness;
5. grounding;
6. observation integrity;
7. context retention;
8. multi-turn continuity;
9. recovery;
10. long-horizon behavior;
11. Hermes/OpenCode compatibility;
12. honest observability.

This is why a single parser test is insufficient as a release criterion.
