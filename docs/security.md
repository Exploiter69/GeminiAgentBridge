# Security

## Credential classes

This project handles two sensitive credential classes:

1. local bridge API keys (`api_keys`);
2. Gemini Web session/authentication material (`cookie_file`).

Both are operator secrets.

## Rules

Never:

- commit session files;
- print cookie values;
- print API keys;
- include authorization headers in bug reports;
- store real credentials in tests;
- bake session material into Docker images;
- claim a credential is valid based only on file presence.

The repository `.gitignore` excludes `cookie.txt`, session files, `config.json`, environment files, logs, and virtual environments.

## Browser extension

The bundled cookie-sync extension reads the active browser session and writes an auth file locally. It is intentionally not a remote credential service.

The resulting file should be treated like a password/session token. Use restrictive permissions and rotate it if exposed.

## Logging

Phase 10 observability is designed to emit structured, credential-redacted lifecycle events. It may record:

- request method/path;
- trace ID;
- message counts;
- tool names;
- durations;
- error classifications;
- sanitized query metadata.

It must not record raw cookies, API keys, authorization headers, session contents, or secret-bearing tool arguments.

## Network boundary

A localhost deployment is the safest default for a local agent stack. If the bridge is exposed to a network, treat it as a network service and configure authentication and network controls accordingly.

The project does not claim that OpenAI protocol compatibility provides transport encryption or internet-facing access control.

## Upstream trust boundary

Gemini Web is an external upstream service whose private web protocol can change independently of this repository. The bridge cannot guarantee availability, model identity, quotas, or account entitlement.

## Tool execution boundary

The bridge does not execute downstream tools. This limits the blast radius of model-generated tool calls: Hermes/OpenCode remain the component responsible for applying filesystem, terminal, Git, and other local side effects.

## Incident response

If a secret is exposed:

1. rotate/revoke the exposed credential or session;
2. remove it from active local configuration;
3. inspect Git history if it was committed;
4. remove affected logs/transcripts where appropriate;
5. report the issue without including the secret itself.

For public issue reports, describe the credential class and failure behavior, not the credential value.

## Scope

This document is an operational security contract, not a formal security audit. The project should not be deployed as an internet-facing service without an external security review appropriate to that deployment.
