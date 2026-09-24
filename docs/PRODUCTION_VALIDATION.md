# Production validation procedure

This is the exact, local-only checklist between the current repository state
and a genuine production-ready claim. Everything here must be run against
your real checkout, real dependencies, and your own authenticated Gemini Web
session — none of it can be done from a sandboxed static audit.

No step here asks you to paste a cookie, key, or session file into anything.

## A. Dependency validation (real libraries, no stubs)

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m pip check
```

Then run the canonical deterministic regression command:

```bash
python -m unittest discover -s tests -p 'test_*.py' -q
```

Expected: **all tests pass**, including `tests/test_extension_contract.py`,
*provided* your checkout has `gemini-cookie-sync-extension/` present (see
"Bug 4" note below — this directory was missing from the archive I audited,
not from your real repository).

## B. Bridge smoke test (no live Gemini call required)

Start the bridge with your real config:

```bash
python -m gemini_web2api --config config.json
```

In another terminal:

```bash
curl -sS http://127.0.0.1:8081/v1/models

curl -sS -H "Authorization: Bearer YOUR_BRIDGE_KEY" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8081/v1/chat/completions \
  -d '{"model":"gemini-3.6-flash","messages":[{"role":"user","content":"Reply with exactly: OK"}],"stream":false}'

curl -sS -H "Authorization: Bearer YOUR_BRIDGE_KEY" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8081/v1/responses \
  -d '{"model":"gemini-3.6-flash","input":[{"type":"input_text","text":"Reply with exactly: OK"}]}'
```

Omit the `Authorization` header only if `api_keys` is empty in your config
(loopback default). Never paste the resulting bridge key or any response
body containing session data into a shared location.

## C. Real Gemini Web test

Using your already-configured local authenticated session (`cookie_file` in
`config.json`), confirm with the *server actually running* (from step B):

1. **Authentication works** — the `Backend health` line the bridge prints at
   startup should not show a failed/expired state.
2. **The account's legitimately available model is resolved** — send a chat
   completion with the model you actually use day-to-day; confirm the
   response comes back as real generated text, not an error.
3. **Normal generation works** — a plain non-tool prompt returns a
   coherent, on-topic reply.
4. **Tool-capable generation works, if your account/model supports it** —
   send one request with a single simple tool (e.g. a `get_time` tool with
   no arguments) and `tool_choice: "auto"`; confirm the response contains a
   `tool_calls` entry with the right name, not an error or apology text.
5. **Upstream 429/error semantics are preserved** — if you have a way to
   trigger a real rate limit (e.g. rapid repeated requests), confirm you get
   a `429` from the bridge, not a `502`/`500` that hides it.

Do not attempt to force step 5 aggressively against a live account beyond a
handful of requests — the point is to observe one real 429, not to stress
Gemini Web itself.

## D. Real OpenCode test

Point OpenCode at the bridge as an OpenAI-compatible provider
(`baseURL: http://127.0.0.1:8081/v1`, using your bridge key if one is
configured). Use whatever provider-configuration mechanism your installed
OpenCode version expects for a custom OpenAI-compatible endpoint — that
configuration surface is OpenCode's, not the bridge's, and is out of scope
for this repository to dictate.

**Exact task** (forces a genuine multi-step trajectory, not a one-shot
prompt), run inside a disposable copy of this repository:

> "In this repository: find every Python file under `gemini_web2api/` that
> imports `httpx` directly. For each one, open it and confirm whether the
> import is guarded by a try/except. Write your findings to a new file
> `audit-result.txt` at the repo root, one line per file, in the form
> `path: guarded` or `path: unguarded`. Then run
> `python -m unittest discover -s tests -p 'test_*.py' -q` and append the
> final result line (pass/fail count) to `audit-result.txt`. Finally, read
> `audit-result.txt` back and tell me what it says."

This forces: repository search/glob → multiple file reads → a file write →
a shell/test run → reading test output → a second file read → final
synthesis — a real multi-tool trajectory of the kind your original report
described failing at step 6+.

**Verify the actual filesystem, not just the agent's final message:**

```bash
cat audit-result.txt
git status   # or: ls -la, if not a git checkout
```

Confirm the file exists, contains one line per matching source file, and
ends with a real test result line copied from the run — not a
paraphrase or a hallucinated summary.

## E. Concurrency test

With the bridge running (step B) and your real session configured, from a
second terminal:

```bash
for i in $(seq 1 12); do
  curl -sS -H "Authorization: Bearer YOUR_BRIDGE_KEY" \
    -H "Content-Type: application/json" \
    http://127.0.0.1:8081/v1/chat/completions \
    -d "{\"model\":\"gemini-3.6-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"Say the number $i and nothing else.\"}],\"stream\":false}" \
    -o "/tmp/gab-concurrency-$i.json" &
done
wait
for i in $(seq 1 12); do
  echo "--- $i ---"; cat "/tmp/gab-concurrency-$i.json"; echo
done
```

This is not a formal benchmark — it's 12 genuinely simultaneous requests.
Check each response's content actually mentions its own number `$i`, not a
different one (that would indicate request-state contamination between
concurrent connections — the same class of bug `test_concurrency_isolation.py`
checks with mocked responses, now checked against your real account).

## F. Soak / stability test (~1 hour)

A minimal practical loop — not a load-testing framework:

```bash
mkdir -p /tmp/gab-soak
i=0
while true; do
  i=$((i+1))
  ts=$(date +%s)
  status=$(curl -sS -o "/tmp/gab-soak/$ts.json" -w "%{http_code}" \
    -H "Authorization: Bearer YOUR_BRIDGE_KEY" \
    -H "Content-Type: application/json" \
    http://127.0.0.1:8081/v1/chat/completions \
    -d "{\"model\":\"gemini-3.6-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"Soak test message $i.\"}],\"stream\":false}")
  echo "$(date -Iseconds) request=$i status=$status" >> /tmp/gab-soak/log.txt
  sleep 15
done
```

Let it run for about an hour (`Ctrl+C` to stop), then review:

```bash
awk '{print $NF}' /tmp/gab-soak/log.txt | sort | uniq -c   # status code histogram
grep -v "status=200" /tmp/gab-soak/log.txt                 # every non-200
```

Also note, over that hour, from the terminal running the bridge itself:
whether the process is still alive and responsive at the end, and whether
its memory usage (`ps -o rss -p <pid>`) grew monotonically or plateaued.
Record any retries, disconnects, malformed tool calls, or crashes you
observe — this document doesn't need every number, just whether the
process survived an hour of real, spaced-out traffic without degrading.

---

## Note on Bug 4 (`gemini-cookie-sync-extension/`)

I could not resolve this by restoring files — I have no source of truth for
their real content and was explicitly told not to fabricate them. Based on
available repository evidence (no git history was included in the archive
I audited, but the CI workflow, the official release-gate script
`scripts/phase13_release_candidate.py`, and both `README.md` and
`docs/live-transport.md` all actively depend on and reference this
directory as a required, maintained part of the project), the evidence
points to **accidental omission from the archive I was given**, not
intentional removal with stale references left behind. Your real local
checkout very likely already has this directory; if `test_extension_contract.py`
fails for you in step A, that would be new information contradicting this
conclusion and worth investigating directly against your git history.
