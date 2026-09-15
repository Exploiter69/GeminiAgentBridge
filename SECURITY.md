# Security

## Authentication material

Gemini Web session exports can contain authentication cookies and related browser
session material. Treat exported files as secrets.

- Never commit session exports, cookie JSON, API keys, or bearer tokens.
- Never paste credential values into issues, pull requests, logs, tests, or chat.
- Keep local session files outside the repository when practical and use restrictive
  filesystem permissions.
- Rotate/revoke a browser session if an exported file is accidentally disclosed.

The bridge intentionally reports authentication failures using error types and safe
status messages rather than logging cookie contents.

## Cookie-sync extension

The `gemini-cookie-sync-extension` is a local-only convenience tool. It uses Chrome
cookie access and downloads because its purpose is to export the current Gemini Web
session. It does not need an external API endpoint and its extension-page CSP is
self-only.

The extension can read sensitive Google cookies by design. Install it only as a
local unpacked extension when you understand that trust boundary. Do not distribute
an exported `gemini-auth.json` containing real session material.

## Network exposure

The Python bridge is intended to bind to loopback by default. Remote binding must
use explicit API-key authentication. Do not expose an unauthenticated instance to
the public internet.

## Reporting

For a suspected security issue, avoid including credentials or session exports in
the report. Describe the affected component and provide a minimal reproducible
case with all authentication material redacted.
