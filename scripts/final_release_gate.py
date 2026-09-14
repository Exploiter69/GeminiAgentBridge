#!/usr/bin/env python3
"""Final release gate for GeminiAgentBridge.

Offline mode proves the repository/package/test contract. ``--live`` adds the
current authenticated Gemini Web smoke and real Hermes/OpenCode matrix. The
script never prints or stores credential material.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
EVIDENCE = ARTIFACTS / "final-release-gate.json"

@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    duration_sec: float | None = None

checks: list[Check] = []


def run(name: str, command: list[str], timeout: int = 300) -> bool:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout,
                              env={**os.environ, "PYTHONUNBUFFERED": "1"})
        output = proc.stdout[-8000:]
        ok = proc.returncode == 0
        checks.append(Check(name, "PASS" if ok else "FAIL", output, round(time.monotonic() - started, 3)))
        return ok
    except subprocess.TimeoutExpired:
        checks.append(Check(name, "FAIL", "timeout", round(time.monotonic() - started, 3)))
        return False


def add(name: str, ok: bool, detail: str) -> None:
    checks.append(Check(name, "PASS" if ok else "FAIL", detail))


def main() -> int:
    parser = argparse.ArgumentParser(description="GeminiAgentBridge final release gate")
    parser.add_argument("--live", action="store_true", help="also run authenticated Gemini Web + real-client checks")
    parser.add_argument("--ci", action="store_true", help="CI mode: validate all deterministic gates while deferring private live evidence")
    parser.add_argument("--cookie-file", help="local Gemini session file; never printed")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--backend", choices=("legacy", "modern", "auto"), default="legacy")
    args = parser.parse_args()

    if args.live and args.ci:
        parser.error("--live and --ci are mutually exclusive")

    add("repository", (ROOT / ".git").is_dir(), str(ROOT))
    add("credential_files_not_tracked", not any((ROOT / name).exists() for name in ("config.json", ".env", "cookie.txt")), "no local credential fixture is present in the checkout")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    add("packaging_metadata", all(x in pyproject for x in (
        'name = "gemini-agent-bridge"', 'requires-python = ">=3.11"',
        'gemini-agent-bridge = "gemini_web2api.__main__:main"',
        'gemini-web2api = "gemini_web2api.__main__:main"',
    )), "pyproject exposes package metadata and both supported entry points")
    add("docker_package_install", "pip install --no-cache-dir --no-deps ." in (ROOT / "Dockerfile").read_text(encoding="utf-8"), "Docker installs the package instead of relying on source-tree imports")

    for name, command in (
        ("unit_full", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]),
        ("compile", [sys.executable, "-m", "compileall", "-q", "gemini_web2api", "scripts", "tests"]),
        ("package_build", [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(ARTIFACTS / "wheels")]),
        ("cli_help", [sys.executable, "-m", "gemini_web2api", "--help"]),
        ("cli_version", [sys.executable, "-m", "gemini_web2api", "--version"]),
        ("trajectory_benchmark", [sys.executable, "scripts/phase9_trajectory_benchmark.py"]),
        ("performance_benchmark", [sys.executable, "scripts/phase12_performance_benchmark.py"]),
        ("long_trajectory", [sys.executable, "scripts/long_trajectory_stress.py"]),
    ):
        run(name, command, 600 if name == "package_build" else 300)

    scan = subprocess.run([
        "grep", "-RInE",
        r"(AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|sk-[A-Za-z0-9_-]{20,})",
        "gemini_web2api", "tests", "scripts", ".github", "docs"
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    add("credential_pattern_scan", scan.returncode == 1, "no known credential patterns found" if scan.returncode == 1 else scan.stdout[-4000:])

    if args.live:
        if not args.cookie_file or not os.path.isfile(args.cookie_file):
            add("live_cookie", False, "--live requires an existing local cookie file")
        else:
            live = run("live_gemini_web", [sys.executable, "scripts/live_gemini_web_test.py", "--cookie-file", args.cookie_file, "--backend", args.backend, "--model", args.model, "--stream"], 600)
            if live:
                for client in ("hermes", "opencode"):
                    if shutil_which(client):
                        run(f"live_{client}", [sys.executable, "scripts/phase8_client_compat.py", f"--{client}", "--live", "--cookie-file", args.cookie_file, "--backend", args.backend, "--model", args.model], 3600)
                    else:
                        add(f"live_{client}", False, f"{client} executable is not installed")
                add("fresh_live_evidence", True, "live commands completed; record their credential-free result in docs/fresh-live-evidence.md")
            else:
                add("fresh_live_evidence", False, "live Gemini Web smoke failed; agent matrix was not attempted")
    elif args.ci:
        add("live_gate", True, "deferred: private authenticated Gemini Web and developer-installed real-agent checks are local release evidence")
    else:
        add("live_gate", False, "not run: final release requires --live with the user's local authenticated session")

    verdict = all(check.status == "PASS" for check in checks)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({"verdict": "GO" if verdict else "NO-GO", "live_requested": args.live, "ci_mode": args.ci, "checks": [asdict(c) for c in checks]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": "GO" if verdict else "NO-GO", "checks": {c.name: c.status for c in checks}}, indent=2, sort_keys=True))
    return 0 if verdict else 1


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
