# GeminiAgentBridge capability matrix

This document is the contract for capability preservation. It intentionally distinguishes bridge compatibility aliases from capabilities actually provided by the selected Gemini Web account/backend.

| Capability | Modern backend | Legacy backend | Policy |
|---|---|---|---|
| Text generation | yes | yes | supported |
| Streaming | yes | yes when httpx is available | supported |
| Local image/document files | yes, via local temporary paths | yes, via legacy upload | preserve attachment order |
| Dynamic account model discovery | yes | no | modern resolves against account |
| Numeric `@think=N` override | no | yes | modern rejects nonzero numeric override explicitly |
| Native model thoughts | yes when upstream returns them | not normalized | preserve metadata internally |
| Temporary chats | yes | yes | explicit request/config only |
| Provider-specific numeric legacy fields | no | yes | never silently send to modern backend |
| Tool execution | no | no | always downstream client-owned |
| Tool schema validation | bridge layer | bridge layer | strict before returning tool calls |
| Tool-call repair | bounded, one repair generation | bounded, one repair generation | no uncontrolled regeneration |
| Chat Completions | yes | yes | primary OpenAI compatibility surface |
| Responses API | yes at protocol layer | yes at protocol layer | mapped through common generation path |
| Google `v1beta` compatibility | yes at protocol layer | yes | compatibility surface, not public Gemini API equivalence |
| Bridge authentication | yes | yes | required for non-loopback bind |
| SSRF-protected remote images | yes | yes | public HTTP(S) only |
| Safe request tracing | production hardened handler | production hardened handler | no credentials/content in events |

## Model policy

The public model IDs are compatibility identifiers. The modern transport uses `GeminiClient.resolve_model()` and account-discovered models rather than translating every identifier to a hardcoded Flash/Pro numeric mode.

An unavailable account model is an upstream capability failure. The bridge must not silently substitute an unrelated model.

## Attachment policy

The HTTP layer may turn image data/URLs into `UploadedFileRef` objects. The modern adapter converts those bytes to short-lived local files because `gemini-webapi` accepts file paths. Temporary files are deleted after the upstream request completes. The legacy backend performs its own upload flow.

## Recovery policy

Tool-call recovery is protocol recovery, not task reasoning. The normal path is one generation followed by at most one repair generation. A transport retry must never duplicate a downstream side-effecting tool execution.

## Evidence levels

- **Unit-tested:** deterministic behavior covered by repository tests.
- **CI-tested:** unit/integration tests pass across the supported Python matrix.
- **Live-tested:** authenticated Gemini Web run performed against the current commit.
- **Agent-tested:** a real Hermes/OpenCode run against the current commit.

Only the last two levels are evidence for current Gemini Web/account availability.
