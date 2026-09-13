#!/usr/bin/env python3
"""OpenCode/Hermes compatibility harness.

Default mode uses a deterministic stub for repeatable protocol tests.
``--live --cookie-file`` runs the same disposable workspaces against the
maintained gemini-webapi backend with the user's local Gemini Web session.
No credentials are printed or persisted by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gemini_web2api.client_compat import COMPATIBILITY_MATRIX
from gemini_web2api.config import CONFIG
from gemini_web2api.hardened_server import HardenedGeminiHandler, HardenedThreadedServer
from gemini_web2api.server import GeminiHandler, ThreadedServer

MODEL = "gemini-3.6-flash"


def _tools(prompt: str) -> list[dict]:
    marker = "Available tools:\n"
    pos = prompt.find(marker)
    if pos < 0:
        return []
    try:
        value, _ = json.JSONDecoder().raw_decode(prompt[pos + len(marker):].lstrip())
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _schema(tool: dict) -> tuple[str, dict]:
    return str(tool.get("name", "")), tool.get("parameters") or {}


def _pick(tools: list[dict], kind: str) -> tuple[str, dict] | None:
    aliases = {
        "list": ("list_files", "list", "glob", "ls"), "read": ("read_file", "read", "cat"),
        "write": ("write_file", "write", "create_file"), "edit": ("edit_file", "edit", "patch"),
        "search": ("search_files", "search", "grep", "glob"), "terminal": ("terminal", "bash", "shell", "run_command", "command"),
    }
    for tool in tools:
        name, schema = _schema(tool)
        low = name.lower()
        if low in aliases[kind] or any(alias in low for alias in aliases[kind]):
            return name, schema
    return None


def _value(key: str, prompt: str) -> object:
    key, p = key.lower(), prompt.lower()
    if key in {"path", "file", "file_path", "filepath", "filename"}: return "summary.txt" if "summary" in p else "sample.txt"
    if key in {"content", "text", "new_content", "file_content"}: return "PHASE8_SUMMARY_OK\n" if "summary" in p else "PHASE8_CREATE_OK\n"
    if key in {"old_string", "old", "find", "search_string"}: return "alpha"
    if key in {"new_string", "replacement", "replace"}: return "PHASE8_EDIT_OK"
    if key in {"pattern", "query", "search_query"}: return "sample.txt"
    if key == "target": return "files"
    if key in {"command", "cmd", "shell"}:
        if "git status" in p: return "git status --short"
        if "git diff" in p: return "git diff --no-ext-diff"
        if "test command" in p: return "python -c \"print('PHASE8_TEST_OK')\""
        return "printf PHASE8_TERMINAL_OK"
    if key in {"workdir", "cwd", "directory"}: return "."
    return None


def _args(schema: dict, prompt: str) -> dict:
    props = schema.get("properties") or {}
    out = {}
    for key in schema.get("required", []) or []:
        value = _value(str(key), prompt)
        if value is not None: out[key] = value
    for key in props:
        if key not in out:
            value = _value(str(key), prompt)
            if value is not None: out[key] = value
    return out


def _marker(prompt: str) -> str:
    match = re.search(r"reply exactly (PHASE8_[A-Z0-9_]+)", prompt)
    return match.group(1) if match else "PHASE8_OK"


def _stub(prompt: str, *args, **kwargs) -> str:
    tools = _tools(prompt)
    if not tools: return _marker(prompt)
    p, n = prompt.lower(), prompt.count("[Tool result for")
    if "long task" in p: sequence = ("list", "read", "terminal", "write")
    elif "multi-step" in p: sequence = ("list", "read", "write")
    elif "search then read" in p: sequence = ("search", "read")
    elif "search then edit" in p: sequence = ("search", "edit")
    elif "create" in p: sequence = ("write",)
    elif "edit" in p: sequence = ("edit",)
    elif any(x in p for x in ("terminal", "test command", "git status", "git diff")): sequence = ("terminal",)
    elif "search" in p: sequence = ("search",)
    elif "list" in p: sequence = ("list",)
    else: sequence = ("read",)
    if n >= len(sequence): return _marker(prompt)
    selected = _pick(tools, sequence[n])
    if selected is None: return _marker(prompt)
    name, schema = selected
    return "```tool_call\n" + json.dumps({"name": name, "arguments": _args(schema, prompt)}) + "\n```"


def _bridge(live: bool, cookie_file: str | None):
    CONFIG["api_keys"] = []
    CONFIG["log_requests"] = False
    if live:
        if not cookie_file or not os.path.isfile(cookie_file):
            raise RuntimeError("--live requires an existing --cookie-file")
        CONFIG["upstream_backend"] = "modern"
        CONFIG["cookie_file"] = cookie_file
        server = HardenedThreadedServer(("127.0.0.1", 0), HardenedGeminiHandler)
        patches = []
    else:
        server = ThreadedServer(("127.0.0.1", 0), GeminiHandler)
        patches = [
            mock.patch("gemini_web2api.server.generate", side_effect=_stub),
            mock.patch("gemini_web2api.server.generate_stream", side_effect=lambda prompt, *a, **kw: iter([_stub(prompt, *a, **kw)])),
        ]
        for patcher in patches: patcher.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, patches


def _hermes_env(root: Path, port: int) -> dict[str, str]:
    home = root / "hermes-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        f"model:\n  default: {MODEL}\n  provider: custom\n  base_url: http://127.0.0.1:{port}/v1\n  api_key: phase8-test\n"
        "terminal:\n  backend: local\n  home_mode: profile\nagent:\n  max_turns: 8\n", encoding="utf-8")
    env = os.environ.copy(); env["HERMES_HOME"] = str(home)
    env.pop("OPENAI_API_KEY", None); env.pop("OPENAI_BASE_URL", None)
    return env


def _opencode_config(workspace: Path, port: int) -> Path:
    config = {
        "$schema": "https://opencode.ai/config.json", "model": f"phase8/{MODEL}",
        "provider": {"phase8": {"npm": "@ai-sdk/openai-compatible", "name": "Phase 8 Bridge Test",
            "options": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "phase8-test"},
            "models": {MODEL: {"name": MODEL, "limit": {"context": 128000, "output": 8192}}}}},
    }
    path = workspace / "opencode-phase8.json"; path.write_text(json.dumps(config, indent=2), encoding="utf-8"); return path


def _run(name: str, prompt: str, workspace: Path, root: Path, port: int) -> dict:
    if name == "hermes":
        env = _hermes_env(root, port)
        cmd = ["hermes", "-z", prompt, "-m", MODEL, "-t", "file,terminal"]
    else:
        env = os.environ.copy(); env.pop("OPENAI_API_KEY", None); env.pop("OPENAI_BASE_URL", None)
        env_home = root / "opencode-home"; env_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(env_home); env["XDG_CONFIG_HOME"] = str(env_home / ".config")
        env["OPENCODE_CONFIG"] = str(_opencode_config(workspace, port))
        cmd = ["opencode", "run", "--print-logs", "--log-level", "DEBUG", "--auto", "--model", f"phase8/{MODEL}", prompt]
    proc = subprocess.run(cmd, cwd=workspace, env=env, text=True, capture_output=True, timeout=180)
    output = (proc.stdout + "\n" + proc.stderr).strip(); marker = _marker(prompt)
    return {"returncode": proc.returncode, "passed": proc.returncode == 0 and marker in output, "marker": marker, "output_tail": output[-2500:]}


def _workspace(root: Path, case) -> Path:
    path = root / case.name; path.mkdir(parents=True, exist_ok=True)
    (path / "sample.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (path / "README.md").write_text("phase8 fixture\n", encoding="utf-8")
    if case.name in {"git_status", "git_diff"}:
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "add", "sample.txt", "README.md"], cwd=path, check=True)
        subprocess.run(["git", "-c", "user.name=Phase8", "-c", "user.email=phase8@example.invalid", "commit", "-qm", "fixture"], cwd=path, check=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes", action="store_true")
    parser.add_argument("--opencode", action="store_true")
    parser.add_argument("--live", action="store_true", help="Use real Gemini Web instead of the deterministic stub")
    parser.add_argument("--cookie-file", type=str, default=None, help="Gemini cookie file used only with --live")
    args = parser.parse_args()
    clients = [name for name, enabled in (("hermes", args.hermes), ("opencode", args.opencode)) if enabled]
    if not clients:
        print(json.dumps({"matrix_cases": len(COMPATIBILITY_MATRIX), "real_clients": "not requested", "self_check": True}, indent=2)); return 0
    original = dict(CONFIG)
    with tempfile.TemporaryDirectory(prefix="gemini-agent-bridge-phase8-") as td:
        root = Path(td); server, thread, patches = _bridge(args.live, args.cookie_file); port = server.server_address[1]; results = {}
        try:
            for client in clients:
                if not shutil.which(client):
                    results[client] = {"passed": False, "error": "client not installed"}; continue
                cases = {}; client_root = root / client; client_root.mkdir()
                for case in COMPATIBILITY_MATRIX:
                    workspace = _workspace(client_root, case)
                    prompt = f"{case.prompt} After actually completing the task, reply exactly PHASE8_{case.name.upper()}_OK."
                    try: cases[case.name] = _run(client, prompt, workspace, root, port)
                    except subprocess.TimeoutExpired: cases[case.name] = {"passed": False, "error": "client timed out"}
                results[client] = {"cases": len(cases), "passed_cases": sum(1 for result in cases.values() if result.get("passed")), "all_pass": all(result.get("passed") for result in cases.values()), "details": cases}
            print(json.dumps({"matrix_cases": len(COMPATIBILITY_MATRIX), "clients": results, "mode": "live" if args.live else "stub"}, indent=2))
            return 0 if all(result.get("all_pass") for result in results.values()) else 1
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            for patcher in patches: patcher.stop()
            CONFIG.clear(); CONFIG.update(original)


if __name__ == "__main__":
    raise SystemExit(main())
