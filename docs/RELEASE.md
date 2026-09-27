# Final release procedure

The remaining release work is now one finite gate. The repository has deterministic packaging, compatibility, performance, documentation, and release checks; current Gemini Web availability and installed real-agent behavior are deliberately verified locally because they require the user's private session and installed clients.

## Offline gate

Run from `fix/full-roadmap` with the normal project virtual environment:

```bash
python scripts/final_release_gate.py
```

This proves:

- package metadata and both entry points;
- Docker installs the package rather than relying on source-tree imports;
- full unit/regression suite;
- compile checks;
- wheel build;
- CLI help/version;
- trajectory and performance benchmarks;
- long-trajectory stress;
- credential-pattern scan.

Offline mode intentionally ends **NO-GO** because a release cannot claim current Gemini Web/account availability without live evidence.

## Final live gate

Use the local authenticated Gemini Web session and the account-visible model already used by the project:

```bash
python scripts/final_release_gate.py --live --cookie-file <local-session-file> --backend legacy --model <account-visible-model>
```

The command runs:

1. fresh non-streaming Gemini Web generation;
2. fresh streaming Gemini Web generation;
3. Hermes real-client compatibility matrix, when `hermes` is installed;
4. OpenCode real-client compatibility matrix, when `opencode` is installed.

The session path is never printed by the gate and credential contents are never stored. The live agent harness uses disposable workspaces.

## Evidence rule

A release is **GO** only when the live command succeeds and the credential-free `docs/fresh-live-evidence.md` record is updated for the current commit. Historical 26/26 Hermes/OpenCode evidence remains regression evidence only; it does not substitute for the fresh transport gate.

## CI

`.github/workflows/final-release-gate.yml` runs the offline gate on the supported Python matrix. CI does not attempt to use private Gemini Web sessions or developer-installed agent binaries.

## Release checklist

- [x] Packaging/entry points defined and tested
- [x] Clean-install/wheel verification automated
- [x] Full deterministic compatibility suite automated
- [x] Real-agent harness automated and credential-safe
- [x] Performance/stability benchmarks automated
- [x] Documentation truth boundary recorded
- [ ] Fresh authenticated Gemini Web non-stream + stream
- [ ] Fresh Hermes real-client matrix
- [ ] Fresh OpenCode real-client matrix
- [ ] Final live GO

No new roadmap phase is created by these checks. A failure belongs to the corresponding existing release item and must be fixed there.
