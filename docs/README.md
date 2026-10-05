# GeminiAgentBridge documentation

This directory is the maintained documentation set for GeminiAgentBridge. The root `README.md` is the quick-start entry point; these pages contain the detailed operational and engineering contracts.

## Start here

| Document | Purpose |
|---|---|
| [`architecture.md`](architecture.md) | Runtime architecture, ownership boundaries, and transport layers |
| [`configuration.md`](configuration.md) | Complete configuration reference and precedence rules |
| [`clients.md`](clients.md) | Hermes, OpenCode, OpenAI SDK, curl, and Gemini CLI integration |
| [`api-compatibility.md`](api-compatibility.md) | Supported HTTP surfaces and compatibility expectations |
| [`troubleshooting.md`](troubleshooting.md) | Evidence-first diagnosis of common failures |
| [`deployment.md`](deployment.md) | Local, Docker, proxy, and process-management guidance |
| [`development.md`](development.md) | Tests, benchmarks, phase gates, and contribution workflow |
| [`security.md`](security.md) | Credential handling, logging, threat boundaries, and reporting rules |
| [`live-transport.md`](live-transport.md) | Modern Gemini Web transport, legacy path, session lifecycle, and current repair status |
| [`RELEASE.md`](RELEASE.md) | One finite final release procedure and Go/No-Go rules |
| [`release-status.md`](release-status.md) | Current release/go-no-go record |
| [`phase8-real-client-evidence.md`](phase8-real-client-evidence.md) | Historical Hermes/OpenCode 26/26 evidence |

## Documentation rules

1. Documentation describes the repository that actually exists; historical behavior is labeled as historical.
2. A synthetic unit test is not presented as proof of live Gemini Web availability.
3. A successful bridge HTTP request is not presented as proof that Gemini Web authentication succeeded.
4. No document contains real cookies, API keys, session files, or authorization headers.
5. Claims about live client compatibility identify whether they came from hosted CI or an explicit local real-client run.
6. Model names are client-facing aliases, not guarantees of a specific Google deployment.
7. The six remaining release items are not an expandable roadmap: they terminate at the single final release gate in `docs/RELEASE.md`.

## Current status

The repository has completed its deterministic release engineering. The current candidate still requires a fresh authenticated Gemini Web generation/stream run and fresh Hermes/OpenCode runs because those depend on the user's private session and installed client versions.
