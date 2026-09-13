#!/usr/bin/env python3
"""Phase 8 real-client compatibility smoke harness.

Drives installed Hermes and/or OpenCode against the real bridge HTTP handler,
but replaces only the upstream Gemini generation function with a deterministic
model stub. This isolates client/bridge compatibility without credentials or
paid inference. Every matrix case uses a fresh disposable workspace.
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
from gemini_web2api.server import GeminiHandler, ThreadedServer

MODEL = "gemini-3.6-flash"


def _extract_tools(prompt: str) -> list[dict]:
    marker = "Available tools:\n"
    pos = prompt.find(marker)
    if pos < 0:
        return []
    try:
        value, _ = json.JSONDecoder().raw_decode(prompt[pos + len(marker):].lstrip())
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _tool_schema(tool: dict) -> tuple[str, dict]:
    name = str(tool.get("name", ""))
    schema = tool.get("parameters") or {}
    return name, schema if isinstance(schema, dict) else {}


def _pick_tool(tools: list[dict], kind: str) -> tuple[str, dict] | None:
    aliases = {
        "read": ("read_file", "read", "cat"),
        "write": ("write_file", "write", "create_file"),
        "edit": ("edit_file", "patch", "edit"),
        "search": ("search_files", "search", "grep", "glob"),
        "terminal": ("terminal", "bash", "shell", "run_command", "command"),
        "list": ("list_files", "glob", "list", "ls"),
    }
    for tool in tools:
        name, schema = _tool_schema(tool)
        low = name.lower()
        if low in aliases[kind] or any(alias in low for alias in aliases[kind]):
            return name, schema
    return None


def _arg_value(key: str, prompt: str) -> object:
    low = key.lower()
    if low in {"path", "file", "file_path", "filepath", "filename"}:
        if "summary" in prompt.lower():
            return "summary.txt"
        if "created" in prompt.lower():
            return "created.txt"
        return "sample.txt"
    if low in {"content", "text", "new_content", "file_content"}:
        if "summary" in prompt.lower():
            return "PHASE8_SUMMARY_OK\n"
        return "PHASE8_CREATE_OK\n"
    if low in {"old_string", "old", "find", "search_string"}:
        return "alpha"
    if low in {"new_string", "replacement", "replace"}:
        return "PHASE8_EDIT_OK"
    if low in {"pattern", "query", "search_query"}:
        return "sample.txt"
    if low == "target":
        return "files"
    if low in {"command", "cmd", "shell"}:
        text = prompt.lower()
        if "git status" in text:
            return "git status --short"
        if "git diff" in text:
            return "git diff --no-ext-diff"
        if "test command" in text:
            return "python -c \"print('PHASE8_TEST_OK')\""
        return "printf PHASE8_TERMINAL_OK"
    if low in {"workdir", "cwd", "directory"}:
        return "."
    if low == "offset":
        return 1
    if low == "limit":
        return 100
    return None


def _arguments_for(schema: dict, prompt: str) -> dict:
    props = schema.get("properties") or {}
    args: dict = {}
    for key in schema.get("required", []) or []:
        value = _arg_value(str(key), prompt)
        if value is not None:
            args[key] = value
    for key in props:
        if key in args:
            continue
        value = _arg_value(str(key), prompt)
        if value is not None and str(key).lower() in {
            "path", "content", "pattern", "query", "command", "workdir",
            "old_string", "new_string", "target",
        }:
            args[key] = value
    return args


def _emit_tool(tool: tuple[str, dict], prompt: str) -> str:
    name, schema = tool
    payload = {"name": name, "arguments": _arguments_for(schema, prompt)}
    return "```tool_call\n" + json.dumps(payload) + "\n```"


def _case_marker(prompt: str) -> str:
    match = re.search(r"reply exactly (PHASE8_[A-Z0-9_]+)", prompt)
    return match.group(1) if match else "PHASE8_OK"


def _stub_generate(prompt: str, *args, **kwargs) -> str:
    tools = _extract_tools(prompt)
    lower = prompt.lower()
    observations = prompt.count("[Tool result for")
    marker = _case_marker(prompt)
    if not tools:
        return marker

    if "long task" in lower or "multi-step" in lower:
        sequence = ["list", "read", "terminal", "write"]
        required = 4
        kind = sequence[min(observations, required - 1)]
    elif "search then read" in lower:
        required = 2
        kind = "search" if observations == 0 else "read"
    elif "search then edit" in lower:
        required = 2
        kind = "search" if observations == 0 else "edit"
    elif "create" in lower:
        required, kind = 1, "write"
    elif "edit" in lower:
        required, kind = 1, "edit"
    elif "terminal" in lower or "test command" in lower or "git status" in lower or "git diff" in lower:
        required, kind = 1, "terminal"
    elif "search" in lower:
        required, kind = 1, "search"
    elif "list" in lower:
        required, kind = 1, "list"
    else:
        required, kind = 1, "read"

    if observations >= required:
        return marker
    selected = _pick_tool(tools, kind)
    if selected is None:
        return "PHASE8_NO_MATCHING_TOOL"
    return _emit_tool(selected, prompt)


def _start_bridge() -> tuple[ThreadedServer, threading.Thread, list]:
    CONFIG["api_keys"] = []
    CONFIG["log_requests"] = False
    server = ThreadedServer(("127.0.0.1", 0), GeminiHandler)
    patches = [
        mock.patch("gemini_web2api.server.generate", side_effect=_stub_generate),
        mock.patch(
            "gemini_web2api.server.generate_stream",
            side_effect=lambda prompt, *a, **kw: iter([_stub_generate(prompt, *a, **kw)]),
        ),
    ]
    for patcher in patches:
        patcher.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, patches


def _hermes_env(root: Path, port: int) -> dict[str, str]:
    home = root / "hermes-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n"
        f"  default: {MODEL}\n"
        "  provider: custom\n"
        f"  base_url: http://127.0.0.1:{port}/v1\n"
        "  api_key: phase8-test\n"
        "terminal:\n  backend: local\n  home_mode: profile\n"
        "agent:\n  max_turns: 8\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_BASE_URL", None)
    return env


def _opencode_config(root: Path, port: int) -> None:
    (root / "opencode.json").write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "model": f"phase8/{MODEL}",
        "permission": "allow",
        "providers": {
            "phase8": {
                "name": "Phase 8 Bridge Test",
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": f"http://127.0.0.1:{port}/v1", "apiKey": "phase8-test"},
                "models": {MODEL: {"name": MODEL}},
            }
        },
    }, indent=2), encoding="utf-8")


def _run_client(name: str, case_prompt: str, workspace: Path, port: int, root: Path) -> dict:
    if name == "hermes":
        env = _hermes_env(root, port)
        cmd = ["hermes", "chat", "--oneshot", "-q", case_prompt, "--toolsets", "file,terminal"]
    else:
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_BASE_URL", None)
        _opencode_config(workspace, port)
        cmd = ["opencode", "run", "--auto", "--model", f"phase8/{MODEL}", case_prompt]
    proc = subprocess.run(cmd, cwd=workspace, env=env, text=True, capture_output=True, timeout=120)
    combined = (proc.stdout + "\n" + proc.stderr).strip()
    marker = _case_marker(case_prompt)
    return {"returncode": proc.returncode, "passed": proc.returncode == 0 and marker in combined,
            "marker": marker, "output_tail": combined[-1500:]}


def _workspace_for_case(root: Path, case) -> Path:
    workspace = root / case.name
    workspace.mkdir(parents=True)
    (workspace / "sample.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (workspace / "README.md").write_text("phase8 fixture\n", encoding="utf-8")
    if case.name.startswith("git_"):
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(["git", "add", "sample.txt", "README.md"], cwd=workspace, check=True)
        subprocess.run(["git", "-c", "user.name=Phase8", "-c", "user.email=phase8@example.invalid", "commit", "-qm", "fixture"], cwd=workspace, check=True)
    return workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes", action="store_true", help="Require and run Hermes")
    parser.add_argument("--opencode", action="store_true", help="Require and run OpenCode")
    args = parser.parse_args()
    clients = [n for n, required in (("hermes", args.hermes), ("opencode", args.opencode)) if required]
    if not clients:
        print(json.dumps({"error": "pass --hermes and/or --opencode for the real-client gate"}, indent=2))
        return 2

    with tempfile.TemporaryDirectory(prefix="gemini-agent-bridge-phase8-") as td:
        root = Path(td)
        server, thread, patches = _start_bridge()
        port = server.server_address[1]
        results = {}
        try:
            for client in clients:
                if not shutil.which(client):
                    results[client] = {"passed": False, "error": "client not installed"}
                    continue
                client_cases = {}
                for case in COMPATIBILITY_MATRIX:
                    workspace = _workspace_for_case(root / client, case)
                    marker = f"PHASE8_{case.name.upper()}_OK"
                    prompt = f"{case.prompt} After actually completing the task, reply exactly {marker}."
                    try:
                        client_cases[case.name] = _run_client(client, prompt, workspace, port, root)
                    except subprocess.TimeoutExpired:
                        client_cases[case.name] = {"passed": False, "error": "client timed out"}
                results[client] = {
                    "cases": len(client_cases),
                    "passed_cases": sum(1 for r in client_cases.values() if r.get("passed")),
                    "all_pass": all(r.get("passed") for r in client_cases.values()),
                    "details": client_cases,
                }
            print(json.dumps({"matrix_cases": len(COMPATIBILITY_MATRIX), "clients": results}, indent=2))
            return 0 if all(r.get("all_pass") for r in results.values()) else 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            for patcher in patches:
                patcher.stop()


if __name__ == "__main__":
    raise SystemExit(main())
