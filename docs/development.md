# Development and verification

## Principles

The project follows evidence-first development:

1. inspect the current repository;
2. establish a baseline;
3. define a measurable hypothesis;
4. make the smallest change;
5. add regression coverage;
6. run focused tests;
7. run the full suite;
8. inspect Git state and diff;
9. independently reproduce important claims;
10. record the remaining risks.

An agent statement such as “tests pass” is not evidence by itself.

## Local test suite

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py'
```

Compile check:

```bash
python -m compileall gemini_web2api scripts tests
```

Whitespace/diff check:

```bash
git diff --check
```

## Benchmarks

The repository contains deterministic benchmark scripts for:

- trajectory reliability;
- Hermes/OpenCode compatibility contracts;
- performance/stability;
- phase-specific regression gates;
- the independent Phase 13 release candidate.

Read the script's `--help` output before running a benchmark. Do not claim a benchmark result unless the command actually ran and its output was recorded.

## Real-client testing

Hosted CI cannot reproduce a developer's installed Hermes/OpenCode environment. Therefore real-client evidence is maintained separately and must identify itself as a local gate.

For transport changes, the minimum live matrix should include:

- direct non-streaming generation;
- direct streaming generation;
- `/v1/models`;
- Hermes smoke task;
- OpenCode smoke task where installed;
- fresh session after restart.

## Credential safety

Tests use fake credentials or redacted configuration. Never add a real Gemini session, API key, or authorization header to a fixture.

A credential-pattern scan is part of the project's release discipline.

## Architecture tests

Tests should preserve the core boundary:

```text
bridge parses/validates
        ≠
bridge executes
```

Any proposed feature that introduces bridge-side shell/filesystem/tool execution requires an explicit architecture review rather than silently expanding the bridge.

## Release evidence

The Phase 13 verifier creates machine-readable evidence and a SHA-256 manifest. The verifier deliberately records that agent claims are not used as verification.

When a later branch changes transport behavior, historical evidence remains historical. It must not be copied forward as proof of the new transport.

## Commit hygiene

Use focused commits and messages that identify the documentation or engineering purpose. Do not commit:

- `config.json`;
- cookies/session files;
- `.env` files;
- local logs containing secrets;
- generated credentials;
- private benchmark artifacts that contain sensitive data.
