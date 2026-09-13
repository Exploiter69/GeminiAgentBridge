#!/usr/bin/env python3
"""Independent Phase 13 release-candidate / Go-No-Go verifier."""
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
PHASE12_BASE = "d8305869cc5ab603afd5fa4b2d44b93483b1c811"

REQUIRED_FILES = (
    "roadmap.md", "gemini_web2api/server.py", "gemini_web2api/context.py",
    "gemini_web2api/observability.py", "gemini_web2api/feature_porting.py",
    "gemini_web2api/performance.py", "tests/test_phase8_compatibility.py",
    "tests/test_phase9_trajectory.py", "tests/test_phase10_observability.py",
    "tests/test_phase11_feature_porting.py", "tests/test_phase12_performance.py",
    "scripts/phase8_client_compat.py", "scripts/phase9_trajectory_benchmark.py",
    "scripts/phase12_performance_benchmark.py",
)
PHASE_COMMITS = {
    "phase8": "44572e9d7db1816865ef53086b0f9ea98b61c7ac",
    "phase9": "f601252d656df2535eb39385415c7ff1b0ec72f8",
    "phase10": "3e14264d07eda9dbcb586fc3981eb2ad9a17ce34",
    "phase11": "c5b7bd7a65a7e9246345fa3d80efd6f59f4638e7",
    "phase12": PHASE12_BASE,
}

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
        proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout,
                              env={**os.environ, "PYTHONUNBUFFERED": "1"})
        output, code = proc.stdout[-12000:], proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = "timeout\n" + (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "timeout"
        code = 124
    check = Check(name, "PASS" if code == 0 else "FAIL", output,
                  " ".join(command), code, round(time.monotonic() - started, 3))
    checks.append(check)
    return check

def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

def add(name: str, status: bool, detail: str) -> None:
    checks.append(Check(name, "PASS" if status else "FAIL", detail))

def defer(name: str, detail: str) -> None:
    checks.append(Check(name, "DEFERRED", detail))

def main() -> int:
    add("repository_root", (ROOT / ".git").exists(), str(ROOT))
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    add("git_head_resolves", len(head) == 40, head)
    add("git_branch", branch not in {"HEAD", ""}, branch)
    status = git("status", "--porcelain")
    add("working_tree_clean", status == "", status or "clean")

    missing = [p for p in REQUIRED_FILES if not (ROOT / p).is_file()]
    add("required_files_exist", not missing, "all required files exist" if not missing else "missing: " + ", ".join(missing))

    failures: list[str] = []
    for phase, sha in PHASE_COMMITS.items():
        try:
            resolved = git("rev-parse", f"{sha}^{{commit}}")
            if resolved != sha:
                failures.append(f"{phase}: resolved {resolved}")
            else:
                subprocess.run(["git", "merge-base", "--is-ancestor", sha, head], cwd=ROOT, check=True)
        except (subprocess.CalledProcessError, subprocess.SubprocessError):
            failures.append(f"{phase}: {sha} is not an ancestor of HEAD")
    add("phase_commits_exist_and_are_ancestors", not failures,
        "all phase commits resolve and are ancestors" if not failures else "; ".join(failures))

    try:
        changed = set(git("diff", "--name-only", PHASE12_BASE, head).splitlines())
        expected = {"scripts/phase13_release_candidate.py", "tests/test_phase13_release_candidate.py",
                    ".github/workflows/phase13-release-candidate.yml", "roadmap.md"}
        add("release_scope_contains_phase13_changes", expected.issubset(changed),
            "changed paths since Phase 12: " + ", ".join(sorted(changed)))
    except subprocess.CalledProcessError as exc:
        add("release_scope_contains_phase13_changes", False, str(exc))

    for name, command in [
        ("phase8_regression", [sys.executable, "-m", "unittest", "tests.test_phase8_compatibility", "-v"]),
        ("phase9_regression", [sys.executable, "-m", "unittest", "tests.test_phase9_trajectory", "-v"]),
        ("phase10_regression", [sys.executable, "-m", "unittest", "tests.test_phase10_observability", "-v"]),
        ("phase11_regression", [sys.executable, "-m", "unittest", "tests.test_phase11_feature_porting", "-v"]),
        ("phase12_regression", [sys.executable, "-m", "unittest", "tests.test_phase12_performance", "-v"]),
        ("full_suite", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]),
        ("compile_check", [sys.executable, "-m", "compileall", "-q", "gemini_web2api", "scripts"]),
        ("phase9_benchmark", [sys.executable, "scripts/phase9_trajectory_benchmark.py"]),
        ("phase12_benchmark", [sys.executable, "scripts/phase12_performance_benchmark.py"]),
    ]:
        run(name, command, timeout=300)

    run("credential_pattern_scan", ["grep", "-RInE",
        r"(AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|sk-[A-Za-z0-9_-]{20,})",
        "gemini_web2api", "tests", "scripts", ".github"], timeout=60)

    if os.environ.get("PHASE13_RUN_REAL_CLIENTS") == "1":
        result = run("real_client_harness", [sys.executable, "scripts/phase8_client_compat.py", "--hermes", "--opencode"], timeout=600)
        if result.exit_code != 0:
            pass
    else:
        defer("real_client_execution",
              "not run in CI: execute PHASE13_RUN_REAL_CLIENTS=1 with both Hermes and OpenCode installed")

    server_text = (ROOT / "gemini_web2api/server.py").read_text(encoding="utf-8")
    forbidden = ("subprocess.run", "subprocess.Popen", "os.system", "os.popen")
    add("bridge_execution_boundary", not any(token in server_text for token in forbidden),
        "server.py contains no direct shell/filesystem execution primitive")

    failed = [asdict(c) for c in checks if c.status == "FAIL"]
    deferred = [c.name for c in checks if c.status == "DEFERRED"]
    verdict = "GO" if not failed and not deferred else "NO-GO"
    payload = {
        "phase": 13, "verdict": verdict, "head": head, "branch": branch,
        "generated_by": "scripts/phase13_release_candidate.py",
        "agent_claims_used_as_verification": False,
        "checks": [asdict(c) for c in checks],
        "failed_checks": [c["name"] for c in failed],
        "deferred_checks": deferred,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    EVIDENCE.write_text(serialized, encoding="utf-8")
    MANIFEST.write_text(hashlib.sha256(serialized.encode()).hexdigest() + "  " + EVIDENCE.name + "\n", encoding="utf-8")
    print(json.dumps({"phase": 13, "verdict": verdict, "head": head,
                      "checks": {c.name: c.status for c in checks},
                      "evidence": str(EVIDENCE.relative_to(ROOT)),
                      "manifest": str(MANIFEST.relative_to(ROOT))}, indent=2, sort_keys=True))
    return 0 if verdict == "GO" else 1

if __name__ == "__main__":
    raise SystemExit(main())
