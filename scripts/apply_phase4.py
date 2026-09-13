#!/usr/bin/env python3
"""Apply the remaining Phase 4 runtime hardening deterministically."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"patch anchor not found: {label} ({path})")
    path.write_text(text.replace(old, new, 1))


def patch_tools() -> None:
    path = ROOT / "gemini_web2api" / "tools.py"
    text = path.read_text()
    if "from .tool_schema import normalize_tool_definitions" not in text:
        text = text.replace("from .grounding import GroundingFacts\n", "from .grounding import GroundingFacts\nfrom .tool_schema import normalize_tool_definitions\n", 1)
    old = '''    if tools and tool_choice != "none":\n        tool_defs = []\n        for tool in tools:\n            fn = tool.get("function", tool) if tool.get("type") == "function" else tool\n            tool_defs.append({\n                "name": fn.get("name", tool.get("name", "")),\n                "description": fn.get("description", tool.get("description", "")),\n                "parameters": fn.get("parameters", tool.get("parameters", {})),\n            })\n        if tool_defs:\n'''
    new = '''    if tools and tool_choice != "none":\n        tool_defs = normalize_tool_definitions(tools)\n        if tool_defs:\n'''
    if old in text:
        text = text.replace(old, new, 1)
    old_json = 'f"Available tools:\\n{json.dumps(tool_defs, indent=2)}"'
    new_json = 'f"Available tools:\\n{json.dumps(tool_defs, ensure_ascii=False, separators=(\",\", \":\"))}"'
    if old_json in text:
        text = text.replace(old_json, new_json, 1)
    path.write_text(text)


def patch_gemini() -> None:
    path = ROOT / "gemini_web2api" / "gemini.py"
    text = path.read_text()
    old = '''            raw = resp.read().decode("utf-8", errors="replace")\n            return extract_response_text(raw)\n'''
    new = '''            raw = resp.read().decode("utf-8", errors="replace")\n            text = extract_response_text(raw)\n            if not text:\n                raise RuntimeError("Gemini upstream returned an empty response")\n            return text\n'''
    if old in text and new not in text:
        text = text.replace(old, new, 1)
    old_stream = '''                for chunk in resp.iter_text():\n'''
    new_stream = '''                emitted = False\n                for chunk in resp.iter_text():\n'''
    if old_stream in text and new_stream not in text:
        text = text.replace(old_stream, new_stream, 1)
    old_delta = '''                            if delta:\n                                emitted_raw_text = t\n                                yield delta\n            return\n'''
    new_delta = '''                            if delta:\n                                emitted_raw_text = t\n                                emitted = True\n                                yield delta\n                if not emitted:\n                    raise RuntimeError("Gemini upstream returned an empty stream")\n            return\n'''
    if old_delta in text and new_delta not in text:
        text = text.replace(old_delta, new_delta, 1)
    path.write_text(text)


def patch_config() -> None:
    path = ROOT / "gemini_web2api" / "config.py"
    anchor = '    "prompt_soft_budget_chars": 0,\n'
    addition = anchor + '    "tool_schema_budget_chars": 30000,\n'
    if '"tool_schema_budget_chars"' not in path.read_text():
        replace_once(path, anchor, addition, "tool schema budget")


def patch_launchers() -> None:
    root = ROOT / "gemini_web2api.py"
    anchor = '    port = CONFIG["port"]\n    server = ThreadedServer((CONFIG["host"], port), GeminiHandler)\n'
    replacement = '''    from gemini_web2api.phase4_runtime import install_phase4_runtime\n    install_phase4_runtime(GeminiHandler)\n\n    port = CONFIG["port"]\n    server = ThreadedServer((CONFIG["host"], port), GeminiHandler)\n'''
    if 'install_phase4_runtime(GeminiHandler)' not in root.read_text():
        replace_once(root, anchor, replacement, "legacy launcher runtime integration")

    main = ROOT / "gemini_web2api" / "__main__.py"
    if main.exists() and 'install_phase4_runtime(GeminiHandler)' not in main.read_text():
        replace_once(main, anchor, replacement.replace("from gemini_web2api.phase4_runtime", "from .phase4_runtime"), "modular launcher runtime integration")


def main() -> None:
    patch_tools()
    patch_gemini()
    patch_config()
    patch_launchers()
    print("Phase 4 runtime patch applied")


if __name__ == "__main__":
    main()
