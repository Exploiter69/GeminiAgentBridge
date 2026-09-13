# Configuration reference

`config.json` is operator-local configuration and is intentionally ignored by Git. Start from `config.example.json`.

## Example

```json
{
  "port": 8081,
  "host": "0.0.0.0",
  "retry_attempts": 3,
  "retry_delay_sec": 2,
  "retry_backoff_multiplier": 2.0,
  "retry_max_delay_sec": 30.0,
  "request_timeout_sec": 180,
  "upstream_backend": "modern",
  "default_model": "gemini-3.6-flash",
  "api_keys": [],
  "cookie_file": null,
  "proxy": null,
  "temporary_chats": false,
  "prompt_soft_budget_chars": 0,
  "tool_schema_budget_chars": 30000,
  "tool_repair_attempts": 1,
  "planner_enabled": false
}
```

## Fields

| Key | Default | Meaning |
|---|---:|---|
| `port` | `8081` | HTTP listen port |
| `host` | `0.0.0.0` | Listen address |
| `retry_attempts` | `3` | Maximum bounded upstream attempts |
| `retry_delay_sec` | `2` | Initial retry delay |
| `retry_backoff_multiplier` | `2.0` | Exponential retry multiplier |
| `retry_max_delay_sec` | `30.0` | Retry delay cap |
| `request_timeout_sec` | `180` | Upstream request timeout |
| `upstream_backend` | `modern` | `modern` for maintained Gemini Web transport; `legacy` only for explicit compatibility |
| `gemini_bl` | project default | Legacy protocol metadata retained for compatibility; not the modern transport's primary model-selection mechanism |
| `auth_user` | `null` | Legacy/account-index compatibility field |
| `xsrf_token` | `null` | Legacy/XSRF compatibility field |
| `default_model` | `gemini-3.6-flash` | Model used when the client omits a model where the API surface permits it |
| `api_keys` | `[]` | Local bridge authentication keys |
| `cookie_file` | `null` | Path to local Gemini Web session/auth data |
| `proxy` | `null` | Explicit HTTP proxy for the modern client; environment proxy settings may also apply |
| `log_requests` | `true` | Request logging switch used by the server layer |
| `temporary_chats` | `false` | Ask the modern client for temporary Gemini chats where supported |
| `prompt_soft_budget_chars` | `0` | Optional prompt-size soft budget; `0` disables this limit |
| `tool_schema_budget_chars` | `30000` | Tool-schema serialization budget |
| `tool_repair_attempts` | `1` | Bounded schema/format repair attempts |
| `planner_enabled` | `false` | Experimental Phase 7 planner flag; keep disabled unless explicitly testing it |

## Configuration precedence

The package starts from built-in defaults, then loads the selected JSON file, then applies command-line overrides.

Current CLI overrides:

```text
--port
--cookie-file
--proxy
```

The configuration file can be selected with:

```bash
python -m gemini_web2api --config /path/to/config.json
```

or with:

```bash
export GEMINI_WEB2API_CONFIG=/path/to/config.json
```

## Authentication

When `api_keys` is empty, the bridge API does not require an application key. When one or more keys are configured, clients must send a matching Bearer token or supported API-key header.

Do not confuse this with Gemini Web authentication. `cookie_file` controls the upstream session and is independent of `api_keys`.

## Session file

The current modern transport reads a local file and extracts the Gemini session values it needs. The repository's cookie-sync extension can export a complete local `gemini-auth.json` file.

The session file is a secret. Recommended permissions:

```bash
chmod 600 /path/to/gemini-auth.json
```

Never place session values directly in Git-tracked documentation or examples.

## Temporary diagnostic configurations

For isolated testing, use a temporary config and a non-production port:

```bash
cat >/tmp/gemini-web2api-test.json <<'EOF'
{
  "host": "127.0.0.1",
  "port": 8083,
  "default_model": "gemini-3.1-pro",
  "api_keys": []
}
EOF

python -m gemini_web2api \
  --config /tmp/gemini-web2api-test.json \
  --cookie-file /path/to/auth-file
```

This avoids changing the operator's real `config.json` while diagnosing upstream behavior.

## Security recommendations

- Bind to `127.0.0.1` when the API is only for local agent clients.
- If binding beyond localhost, configure `api_keys` and place the service behind an appropriate network boundary.
- Keep session files outside the repository when possible.
- Never log authorization headers, cookies, API keys, or session files.
- Rotate a Gemini session if it is exposed.
