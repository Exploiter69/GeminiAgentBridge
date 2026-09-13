# Cloudflare Worker variant

> **Status:** legacy / experimental deployment variant.
>
> The primary maintained project path is the local Python package documented in the repository root and `docs/`. This Worker implementation is a separate deployment surface built around Gemini Web's private web protocol and can become stale independently of the maintained Python transport.

## What this is

`cloudflare/worker.js` exposes an OpenAI-compatible HTTP surface from a Cloudflare Worker. It is useful for experimentation where a remote edge endpoint is required.

It is **not** the reference implementation for the current Gemini Web transport repair.

## Important differences from the Python server

| Area | Python package | Cloudflare Worker |
|---|---|---|
| Primary entrypoint | `python -m gemini_web2api` | `cloudflare/worker.js` |
| Maintained upstream client | `gemini-webapi` | private web protocol code in Worker |
| Default deployment | local/self-hosted | Cloudflare edge |
| Session storage | local auth file | Worker configuration/secrets |
| Current repair coverage | yes | no |
| Release gate | current project gate | separate validation required |

## Deployment

The Worker can be deployed using Cloudflare's normal Worker tooling/dashboard. Keep all authentication material in Cloudflare secrets or environment configuration; never paste it into `worker.js` or commit it.

After deployment, verify the actual routes implemented by the current `worker.js` rather than assuming the Python API and Worker are perfectly identical.

## OpenAI-compatible request

The Worker historically exposes `/v1/chat/completions` and `/v1/models`.

Example shape:

```bash
curl https://YOUR-WORKER/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer YOUR_WORKER_KEY' \
  -d '{
    "model": "gemini-3.6-flash",
    "messages": [{"role":"user","content":"Hello"}],
    "stream": false
  }'
```

Never put a real Worker key or Gemini session value into documentation.

## Authentication/session configuration

The Worker code has historically supported cookie/session-related environment variables. Treat them as secrets.

Do not document or rely on hard-coded cookie values. Rotate any credential that is exposed.

## HTTP 405 / 429 behavior

A 405 or 429 from this Worker is an upstream/private-protocol compatibility signal. Do not assume that changing a build label alone makes the transport current.

The Python repair branch intentionally moved away from the historical direct `StreamGenerate` default because Gemini Web can change its private RPC surface. The Worker implementation has not received the same maintained-client migration.

Likewise, fingerprint rotation or multiple-account rotation should not be described as a guaranteed way to bypass Google rate limits or anti-abuse controls. Upstream policy remains authoritative.

## Security

A public Worker is a network service. Before exposing it:

- configure authentication;
- keep session material in secrets;
- avoid logging request bodies or credentials;
- apply an appropriate rate policy;
- do not commit environment values;
- review Cloudflare's current Worker limits and pricing independently of this repository.

## When to use this variant

Use the Worker directory only when you specifically need an edge deployment and accept that it has a separate maintenance and compatibility lifecycle.

For the actively maintained GeminiAgentBridge path, use the Python package and follow:

- `README.md`
- `docs/live-transport.md`
- `docs/deployment.md`
- `docs/troubleshooting.md`
