# Troubleshooting

The project is easiest to debug when each layer is tested separately.

## 1. Confirm which server is running

If a port behaves unexpectedly:

```bash
ss -ltnp | grep ':8081'
```

Then inspect the command line of the owning process:

```bash
ps -fp <PID>
```

The historical `python gemini_web2api.py` process and the maintained `python -m gemini_web2api` process are different execution paths.

## 2. `/v1/models` works but generation fails

This usually means the local HTTP layer is healthy but the upstream generation path is not.

Check for:

- Gemini Web session authentication;
- upstream 429/throttle responses;
- proxy/network failures;
- missing `gemini-webapi` dependency;
- model/session compatibility.

Do not infer upstream health from `/v1/models` alone.

## 3. `Account status: UNAUTHENTICATED`

This comes from the maintained Gemini Web client when the supplied session is invalid or expired.

Resolution:

1. sign in to Gemini in the browser;
2. refresh/export a new local auth file with the repository extension;
3. update only the `cookie_file` path;
4. restart the bridge;
5. retest generation.

Never paste the session file or its values into an issue or chat.

## 4. HTTP 405 mentioning `StreamGenerate`

This is the signature of the historical direct transport.

First determine the process:

```bash
ss -ltnp | grep ':8081'
ps -fp <PID>
```

The maintained package path is:

```bash
python -m gemini_web2api
```

The top-level historical script is:

```bash
python gemini_web2api.py
```

Do not compare their upstream behavior as though they were the same transport.

## 5. HTTP 429

A 429 from Gemini Web is an upstream condition. Possible causes include account/session state, rate limits, anti-abuse controls, network/proxy characteristics, or upstream policy changes.

The bridge must not hide a persistent upstream 429 by pretending the request succeeded.

Collect only redacted evidence:

```text
HTTP status
error type
timestamp
retry count
transport name
```

Do not collect or paste cookies or authorization headers.

## 6. `gemini-webapi is not installed`

Make sure the project virtual environment is active:

```bash
source .venv/bin/activate
which python
python -c 'import gemini_webapi; print(gemini_webapi.__file__)'
python -c 'from gemini_webapi import GeminiClient; print("GeminiClient OK")'
```

The maintained client currently requires Python 3.11+.

## 7. `Address already in use`

Find the owner:

```bash
ss -ltnp | grep ':8083'
```

For an intentionally disposable diagnostic server:

```bash
fuser -k 8083/tcp
```

Avoid killing an unrelated production service.

## 8. Streaming returns an initial chunk then fails

This can happen when the bridge commits the downstream SSE response before the upstream request has produced its first useful model data.

At that point a normal HTTP JSON error can no longer be sent. The client must treat an incomplete stream as a failed generation unless a valid terminal completion is observed.

This is a known repair item, not evidence that the upstream generation succeeded.

## 9. Hermes/OpenCode behaves incorrectly

Separate the client from the bridge:

1. call `/v1/models` directly;
2. send a minimal direct `/v1/chat/completions` request;
3. inspect the returned tool call/response;
4. repeat from the real client;
5. compare the exact request shape and returned protocol data.

The bridge should not be blamed for a client-side CWD, planner, or tool-execution problem without evidence.

## 10. Wrong workspace/path in an agent answer

Check:

- requested working directory;
- agent launch directory;
- explicit CWD configuration;
- returned tool name and arguments;
- actual tool observation from Hermes/OpenCode;
- bridge prompt/context facts;
- context compaction;
- whether the same session had unrelated history.

The bridge must never solve this by hard-coding the operator's current directory.

## 11. Credential exposure

If a Gemini session or bridge key was printed, pasted, committed, or otherwise exposed:

1. stop using the exposed session/key;
2. rotate/re-export it;
3. remove it from local logs/transcripts where appropriate;
4. check Git history if it was committed;
5. do not add the value to a bug report.

The repository's credential-safety rule is stronger than ordinary debug convenience.
