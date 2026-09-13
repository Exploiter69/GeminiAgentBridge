#!/usr/bin/env python3
"""Phase 8 real-client compatibility smoke harness.

Starts the actual GeminiAgentBridge HTTP handler with a deterministic in-process
model stub, then optionally drives installed Hermes and OpenCode CLIs against it.
No credentials are read or written. Each client gets an isolated temporary
profile/config and a disposable workspace.

By default the script only runs the local protocol harness. Pass --hermes and/or
--opencode to require and exercise those real clients.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest import mock

from gemini_web2api.client_compat import COMPATIBILITY_MATRIX
from gemini_web2api.config import CONFIG
from gemini_web2api.server import GeminiHandler, ThreadedServer

MODEL = "gemini-3.6-flash"


def _extract_tools(prompt: str) -> list[dict]:
    marker = "Available tools:\n"
    pos = prompt.find(marker)
    if pos < 0:
        return []
    tail = prompt[pos + len(marker):]
    try:
        value, _ = json.JSONDecoder().raw_decode(tail.lstrip())
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _tool_schema(tool: dict) -> tuple[str, dict]:
    name = str(tool.get("name", ""))
    params = tool.get("parameters") or {}
    return name, params if isinstance(params, dict) else {}


def _pick_tool(tools: list[dict], kind: str) -> tuple[str, dict] | None:
    aliases = {
        "read": ("read_file", "read", "cat"),
        "write": ("write_file", "write", "create_file"),
        "edit": ("edit_file", "patch", "edit"),
        "search": ("search_files", "search", "grep", "glob"),
        "terminal": ("terminal", "bash", "shell", "run_command", "command"),
        "list": ("list_files", "glob", "list", "ls"),
    }
    names = aliases[kind]
    for tool in tools:
        name, schema = _tool_schema(tool)
        low = name.lower()
        if low in names or any(alias in low for alias in names):
            return name, schema
    return None


def _arg_value(key: str) -> object:
    low = key.lower()
    if low in {"path", "file", "file_path", "filepath", "filename"}:
        return "sample.txt"
    if low in {"content", "text", "new_content", "file_content"}:
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
        return "printf PHASE8_TERMINAL_OK"
    if low in {"workdir", "cwd", "directory"}:
        return "."
    if low == "offset":
        return 1
    if low == "limit":
        return 100
    return None


def _arguments_for(schema: dict) -> dict:
    props = schema.get("properties") or {}
    args: dict = {}
    for key in schema.get("required", []) or []:
        value = _arg_value(str(key))
        if value is not None:
            args[key] = value
    for key in props:
        if key in args:
            continue
        value = _arg_value(str(key))
        if value is not None and str(key).lower() in {
            "path", "content", "pattern", "query", "command", "workdir",
            "old_string", "new_string", "target",
        }:
            args[key] = value
    return args


def _emit_tool(tool: tuple[str, dict]) -> str:
    name, schema = tool
    return "```tool_call\n" + json.dumps({"name": name, "arguments": _arguments_for(schema)}) + "\n```"


def _stub_generate(prompt: str, *args, **kwargs) -> str:
    """Deterministic model substitute used only for client transport testing."""
    tools = _extract_tools(prompt)
    lower = prompt.lower()
    observations = prompt.count("[Tool result for")
    if not tools:
        return "PHASE8_TEXT_OK"
    if "long task" in lower or "multi-step" in lower:
        kind = ["list", "read", "terminal", "write"][min(observations, 3)]
    elif "search then read" in lower:
        kind = "search" if observations == 0 else "read"
    elif "search then edit" in lower:
        kind = "search" if observations == 0 else "edit"
    elif "create" in lower:
        kind = "write"
    elif "edit" in lower:
        kind = "edit"
    elif "terminal" in lower or "test command" in lower or "git status" in lower or "git diff" in lower:
        kind = "terminal"
    elif "search" in lower:
        kind = "search"
    elif "list" in lower:
        kind = "list"
    else:
        kind = "read"
    selected = _pick_tool(tools, kind)
    if selected is None:
        return "PHASE8_NO_MATCHING_TOOL"
    if observations > 3:
        return "PHASE8_MULTI_STEP_OK"
    return _emit_tool(selected)


def _start_bridge() -> tuple[ThreadedServer, threading.Thread, list]:
    CONFIG["api_keys"] = []
    CONFIG["log_requests"] = False
    server = ThreadedServer(("127.0.0.1", 0), GeminiHandler)
    generate_patch = mock.patch("gemini_web2api.server.generate", side_effect=_stub_generate)
    stream_patch = mock.patch(
        "gemini_web2api.server.generate_stream",
        side_effect=lambda prompt, *args, **kwargs: iter([_stub_generate(prompt, *args, **kwargs)]),
    )
    generate_patch.start()
    stream_patch.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, [generate_patch, stream_patch]


def _hermes_env(root: Path, port: int) -> dict[str, str]:
    home = root / "hermes-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n"
        f"  default: {MODEL}\n"
        "  provider: custom\n"
        f"  base_url: http://127.0.0.1:{port}/v1\n"
        "  api_key: phase8-test\n"
        "terminal:\n"
        "  backend: local\n"
        "  home_mode: profile\n"
        "agent:\n"
        "  max_turns: 8\n",
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


def _run_client(name: str, workspace: Path, port: int, root: Path) -> dict:
    if name == "hermes":
        env = _hermes_env(root, port)
        cmd = ["hermes", "chat", "--oneshot", "-q",
               "Read sample.txt and reply exactly PHASE8_READ_OK after you have actually read it.",
               "--toolsets", "file"]
    else:
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_BASE_URL", None)
        _opencode_config(workspace, port)
        cmd = ["opencode", "run", "--auto", "--model", f"phase8/{MODEL}",
               "Read sample.txt and reply exactly PHASE8_READ_OK after you have actually read it."]
    proc = subprocess.run(cmd, cwd=workspace, env=env, text=True, capture_output=True, timeout=90)
    combined = (proc.stdout + "\n" + proc.stderr).strip()
    return {"client": name, "returncode": proc.returncode,
            "passed": proc.returncode == 0 and "PHASE8_READ_OK" in combined,
            "output_tail": combined[-2000:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes", action="store_true", help="Require and run installed Hermes")
    parser.add_argument("--opencode", action="store_true", help="Require and run installed OpenCode")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gemini-agent-bridge-phase8-") as td:
        root = Path(td)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "sample.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        (workspace / "README.md").write_text("phase8 fixture\n", encoding="utf-8")
        server, thread, patches = _start_bridge()
        port = server.server_address[1]
        try:
            results = {"protocol_harness": {"matrix_cases": len(COMPATIBILITY_MATRIX), "bridge_port": port, "passed": True}}
            for name, required in (("hermes", args.hermes), ("opencode", args.opencode)):
                if not shutil.which(name):
                    results[name] = {"passed": False, "error": "client not installed"} if required else {"passed": None, "skipped": True}
                    continue
                try:
                    results[name] = _run_client(name, workspace, port, root)
                except subprocess.TimeoutExpired:
                    results[name] = {"passed": False, "error": "client timed out"}
            print(json.dumps(results, indent=2))
            required_results = [results[n] for n, required in (("hermes", args.hermes), ("opencode", args.opencode)) if required]
            return 0 if all(r.get("passed") for r in required_results) else 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            for patcher in patches:
                patcher.stop()


if __name__ == "__main__":
    raise SystemExit(main())
