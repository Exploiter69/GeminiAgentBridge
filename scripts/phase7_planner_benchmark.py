"""Deterministic Phase 7 planner experiment benchmark.

This benchmark compares planner decisions with a Gemini-only baseline modelled
as "no synthesized tool call". It does not execute tools and requires no
credentials or live network access.
"""
import json
from gemini_web2api.planner import propose


def tool(name, description, properties=None, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {},
                           "required": required or [], "additionalProperties": False}}}

READ = tool("read_file", "Read a file from the workspace.", {"path": {"type": "string"}}, ["path"])
SEARCH = tool("search", "Search the codebase for a query.", {"query": {"type": "string"}}, ["query"])
EDIT = tool("edit_file", "Edit or modify a file.", {"path": {"type": "string"}}, ["path"])
LIST = tool("list_files", "List files in a directory.")

CASES = [
    ("obvious_search", 'Search for "TODO"', [SEARCH]),
    ("obvious_list", "List files", [LIST]),
    ("obvious_read", 'Read "sample.txt"', [READ]),
    ("obvious_edit", 'Edit "app.py"', [EDIT]),
    ("ambiguous", "Help me with the project", [READ, SEARCH, EDIT]),
    ("multi_step", 'Search for "TODO" then edit app.py', [SEARCH, EDIT]),
    ("wrong_path", "Read the current file", [READ]),
]


def main():
    results = []
    for name, request, tools in CASES:
        p = propose(request, tools)
        results.append({
            "case": name,
            "confidence": p.confidence,
            "tool": p.tool_name,
            "arguments": p.arguments,
            "planner_synthesizes": p.should_synthesize,
            "gemini_only_baseline_synthesizes": False,
        })
    high = sum(r["planner_synthesizes"] for r in results)
    unsafe = sum(r["planner_synthesizes"] for r in results if r["case"] in {"ambiguous", "multi_step", "wrong_path"})
    print(json.dumps({"cases": results, "high_confidence_calls": high, "unsafe_syntheses": unsafe}, indent=2))
    if unsafe:
        raise SystemExit("unsafe planner synthesis detected")


if __name__ == "__main__":
    main()
