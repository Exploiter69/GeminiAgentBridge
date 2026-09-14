#!/usr/bin/env python3
"""Independent repository-level release-candidate / Go-No-Go verifier."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts"
EVIDENCE = ARTIFACT_DIR / "phase13-release-candidate.json"
MANIFEST = ARTIFACT_DIR / "phase13-release-candidate.sha256"

@dataclass
class Check:
    name: str
    status: str
    detail: str
    command: str | None = None
    exit_code: int | None = None
    duration_sec: float | None = None

checks: list[Check] = []


def run(name: str, command: list[str], *, timeout: int = 300) -> Check:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        output, code = proc.stdout[-12000:], proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = "timeout\n" + (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "timeout"
        code = 124
    check = Check(name, "PASS" if code == 0 else "FAIL", output, " ".join(command), code, round(time.monotonic() - started, 3))
    checks.append(check)
    return check


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def add(name: str, status: bool, detail: str) -> None:
    checks.append(Check(name, "PASS" if status else "FAIL", detail))


def main() -> int:
    add("repository_root", (ROOT / ".git").exists(), str(ROOT))
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    add("git_head_resolves", len(head) == 40, head)
    add("git_branch", branch not in {"", "HEAD"} or os.environ.get("GITHUB_ACTIONS") == "true", branch or "detached CI merge checkout")
    add("working_tree_clean", git("status", "--porcelain") == "", git("status", "--porcelain") or "clean")

    required = [
        "gemini_web2api/server.py", "gemini_web2api/modern.py", "gemini_web2api/gemini.py",
        "gemini_web2api/models.py", "gemini_web2api/tools.py", "gemini_web2api/context.py",
        "gemini_web2api/protocol.py", "gemini_web2api/backend.py", "gemini_web2api/observability.py",
        "gemini_web2api/feature_porting.py", "gemini_web2api/performance.py",
        "tests/test_modern_transport.py", "tests/test_modern_safety.py",
        "tests/test_phase10_observability.py", "tests/test_phase11_feature_porting.py",
        "tests/test_phase12_performance.py", "tests/test_phase13_release_candidate.py",
    ]
    missing = [p for p in required if not (ROOT / p).is_file()]
    add("required_files_exist", not missing, "all required files exist" if not missing else "missing: " + ", ".join(missing))

    for name, command in [
        ("phase10_regression", [sys.executable, "-m", "unittest", "tests.test_phase10_observability", "-q"]),
        ("phase11_regression", [sys.executable, "-m", "unittest", "tests.test_phase11_feature_porting", "-q"]),
        ("phase12_regression", [sys.executable, "-m", "unittest", "tests.test_phase12_performance", "-q"]),
        ("full_suite", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]),
        ("compile_check", [sys.executable, "-m", "compileall", "-q", "gemini_web2api", "scripts"]),
        ("phase9_benchmark", [sys.executable, "scripts/phase9_trajectory_benchmark.py"]),
        ("phase12_benchmark", [sys.executable, "scripts/phase12_performance_benchmark.py"]),
    ]:
        run(name, command, timeout=300)

    scan = run("credential_pattern_scan", ["grep", "-RInE", r"(AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|sk-[A-Za-z0-9_-]{20,})", "gemini_web2api", "tests", "scripts", ".github"], timeout=60)
    if scan.exit_code == 1:
        scan.status = "PASS"
        scan.detail = "no credential patterns found"

    server_text = (ROOT / "gemini_web2api/server.py").read_text(encoding="utf-8")
    forbidden = ("subprocess.run", "subprocess.Popen", "os.system", "os.popen")
    add("bridge_execution_boundary", not any(token in server_text for token in forbidden), "server.py contains no direct shell/filesystem execution primitive")

    failed = [asdict(c) for c in checks if c.status == "FAIL"]
    verdict = "GO" if not failed else "NO-GO"
    payload = {
        "phase": 13,
        "verdict": verdict,
        "head": head,
        "branch": branch,
        "generated_by": "scripts/phase13_release_candidate.py",
        "agent_claims_used_as_verification": False,
        "checks": [asdict(c) for c in checks],
        "failed_checks": [c["name"] for c in failed],
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    EVIDENCE.write_text(serialized, encoding="utf-8")
    MANIFEST.write_text(hashlib.sha256(serialized.encode()).hexdigest() + "  " + EVIDENCE.name + "\n", encoding="utf-8")

    print(json.dumps({"phase": 13, "verdict": verdict, "head": head, "failed_checks": [c["name"] for c in failed]}, indent=2, sort_keys=True))
    if failed:
        print("\n=== RELEASE GATE FAILURE DETAILS ===")
        for check in failed:
            print(f"\n[{check['name']}] exit={check.get('exit_code')} command={check.get('command')}")
            print(check.get("detail", "")[-12000:])
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
