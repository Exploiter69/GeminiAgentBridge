# Fresh Live Verification Evidence

This file is intentionally credential-free. It is the release gate's durable record
for the current repaired transport and must be updated only from fresh local runs.

## Authenticated Gemini Web smoke

Status: **PASS**

Fresh result:
- `LIVE_GEMINI_WEB_OK`
- `BACKEND=legacy`
- `MODEL_RESOLVED=gemini-3.6-flash`
- `THOUGHTS_PRESENT=False`
- `LIVE_GEMINI_WEB_STREAM_OK`

The maintained legacy Gemini Web transport successfully generated a semantic
response and completed the streaming verification on the current
`fix/full-roadmap` branch.

Required markers after a successful local run:

- `LIVE_GEMINI_WEB_OK`
- `LIVE_GEMINI_WEB_STREAM_OK`
- resolved account-visible model name

Command shape:

```text
python scripts/live_gemini_web_test.py --cookie-file <local-session-file> --stream --model <account-visible-model>
```

## Hermes

Status: **NOT RUN**

Required result: all compatibility cases pass against the repaired branch using the
same fresh authenticated session and account-visible model.

## OpenCode

Status: **NOT RUN**

Required result: all compatibility cases pass against the repaired branch using the
same fresh authenticated session and account-visible model.

## Release rule

Do not record cookie contents, API keys, authorization headers, session paths, or
other authentication material here. A run is evidence only when its output is from
the current `fix/full-roadmap` code, not from historical Phase 8 evidence.
