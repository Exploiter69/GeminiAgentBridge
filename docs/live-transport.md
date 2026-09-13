# Live Gemini Web transport

## Why there are two transports

The original project talked directly to Gemini Web's `StreamGenerate` endpoint. Gemini Web is a private web application and its internal protocol changes over time. A route that worked previously can return HTTP 405 or otherwise stop matching the current frontend.

The repair branch therefore separates:

- **modern transport** — maintained `gemini-webapi` client;
- **legacy transport** — the old direct `StreamGenerate` implementation retained only for explicit compatibility.

The package default is `modern`.

## Modern backend

The modern backend lives in `gemini_web2api/modern.py` and uses `gemini-webapi==2.1.1`.

Key design properties:

- one persistent `GeminiClient` rather than one client per request;
- a dedicated background asyncio event loop for synchronous bridge handlers;
- automatic client/session refresh where the upstream library supports it;
- bounded retry policy inherited from bridge configuration;
- client reset on authentication/session/model-class failures;
- model-tier mapping rather than hard-coded stale numeric deployment IDs;
- no downstream shell/filesystem/tool execution;
- credential-redacted logging.

## Session requirements

The modern backend requires an authenticated Gemini Web session for the current implementation. `cookie_file` points to local session data.

A session can be syntactically valid while no longer being authenticated. The upstream client can report a state such as:

```text
Account status: UNAUTHENTICATED
Session is not authenticated or cookies have expired
```

That is an upstream session problem, not proof that the bridge selected the wrong HTTP route.

## Browser sync extension

`gemini-cookie-sync-extension/` provides a local Chrome extension that reads the active Gemini session and exports `gemini-auth.json`. The extension is intended to keep session material local.

See:

- `gemini-cookie-sync-extension/README.txt`
- `gemini-cookie-sync-extension/SETUP.md`

Treat the generated file as a credential. Never paste it into a terminal transcript, issue, pull request, or chat.

## Current live-test status

The repair branch has been tested far enough to establish that:

1. the package entrypoint selects the modern transport;
2. `gemini-webapi` is importable in the project virtual environment;
3. the modern client initializes against the provided local session file;
4. the tested session was reported by the upstream library as unauthenticated/expired;
5. therefore a successful authenticated Gemini Web generation has **not yet been established** on the repair branch.

This distinction is deliberate. The project must not claim a live upstream pass based only on package initialization or `/v1/models`.

## Legacy backend

The legacy implementation remains available through:

```json
{
  "upstream_backend": "legacy"
}
```

It is not the default and should not be used as evidence that the modern transport is healthy.

If logs show an HTTP 405 mentioning `StreamGenerate`, first determine which process owns the listening port and how it was started. A historical top-level `python gemini_web2api.py` process can still expose the legacy implementation while `python -m gemini_web2api` uses the repaired package server.

## Recommended diagnostic separation

Use a dedicated test port for transport diagnosis:

```bash
python -m gemini_web2api \
  --config /tmp/gemini-web2api-test.json \
  --cookie-file /path/to/auth-file
```

Then inspect:

```bash
ss -ltnp | grep ':8083'
```

and test `/v1/models` before generation.

Never run two unrelated bridge implementations on the same port during diagnosis.

## Failure taxonomy

| Evidence | Interpretation |
|---|---|
| `StreamGenerate` + 405 | likely legacy/stale transport |
| modern client says unauthenticated | expired/invalid Gemini session |
| modern client returns 429 | upstream throttling/anti-abuse/network behavior |
| modern client import failure | environment/dependency problem |
| bridge 401/403 before upstream request | local bridge authentication |
| partial SSE followed by upstream failure | downstream stream error propagation issue |

## Release requirement

A modern transport change is not releasable merely because unit tests pass. The release gate requires:

1. deterministic test suite green;
2. package import/compile checks green;
3. transport-specific tests green;
4. a fresh authenticated live Gemini Web generation check;
5. streaming verification;
6. real Hermes/OpenCode smoke coverage against the resulting server;
7. no credential leakage in source or evidence.
