"""Deterministic Phase 12 performance/stability benchmark.

This benchmark measures local bridge work only. It never calls Gemini Web and
never executes downstream tools. Machine-dependent timings are reported as
observations, not hard pass/fail thresholds; correctness invariants are gates.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from gemini_web2api.context import compact_messages
from gemini_web2api.performance import RetryPolicy, benchmark_callable, stable_report
from gemini_web2api.tool_schema import normalize_tool_definitions
from gemini_web2api.tools import build_tool_prompt, parse_tool_calls


def _trajectory(size: int = 240) -> list[dict]:
    messages = [{"role": "system", "content": "stable contract"}]
    for index in range(size):
        messages.extend([
            {"role": "user", "content": f"task {index}: inspect project state"},
            {"role": "assistant", "content": f"planning step {index}"},
            {"role": "tool", "name": "read_file", "content": f"observation {index}"},
        ])
    messages.append({"role": "user", "content": "final task: verify target.py"})
    return messages


def _tools(count: int = 24) -> list[dict]:
    return [
        {
            "name": f"tool_{i}",
            "description": "Useful local tool. " * 30,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace path " * 20},
                    "mode": {"type": "string", "enum": ["safe", "fast"]},
                },
                "required": ["path"],
            },
        }
        for i in range(count)
    ]


def main() -> int:
    messages = _trajectory()
    tools = _tools()
    policy = RetryPolicy(attempts=5, base_delay_sec=1, backoff_multiplier=2, max_delay_sec=5)
    assert [policy.delay_for_retry(i) for i in range(5)] == [1, 2, 4, 5, 5]

    _, context_sample = benchmark_callable(
        "context_compaction",
        lambda: compact_messages(messages, 5000),
        iterations=30,
    )
    normalized, schema_sample = benchmark_callable(
        "tool_schema_normalization",
        lambda: normalize_tool_definitions(tools, max_chars=12000),
        iterations=30,
    )
    _, prompt_sample = benchmark_callable(
        "tool_prompt_build",
        lambda: build_tool_prompt(tools),
        iterations=30,
    )

    text = "\n".join(
        f'```tool_call\n{{"name":"tool_{i}","arguments":{{"path":"file_{i}.py"}}}}\n```'
        for i in range(8)
    )
    _, parser_sample = benchmark_callable(
        "tool_call_parser",
        lambda: parse_tool_calls(text),
        iterations=30,
    )

    # Concurrent requests exercise only deterministic local work.
    def concurrent_compaction() -> list[dict]:
        with ThreadPoolExecutor(max_workers=8) as executor:
            return list(executor.map(lambda _: compact_messages(messages, 5000)[1], range(16)))

    concurrent_result, concurrent_sample = benchmark_callable(
        "concurrent_compaction",
        concurrent_compaction,
        iterations=5,
    )

    compacted, context_meta = compact_messages(messages, 5000)
    parsed_text, parsed_calls = parse_tool_calls(text)
    assert context_meta["compacted"] is True
    assert "final task: verify target.py" in json.dumps(compacted)
    assert "observation 239" in json.dumps(compacted)
    assert len(normalized) == len(tools)
    assert all("parameters" in tool for tool in normalized)
    assert parsed_text == ""
    assert len(parsed_calls) == 8
    assert len(concurrent_result) == 16
    assert {item["elided_messages"] for item in concurrent_result} == {len(messages) - len(compacted) - 1}

    report = stable_report([context_sample, schema_sample, prompt_sample, parser_sample, concurrent_sample])
    print(json.dumps({
        "phase": 12,
        "status": "PASS",
        "iterations": 30,
        "retry_delays": [policy.delay_for_retry(i) for i in range(5)],
        "context": context_meta,
        "tool_count": len(normalized),
        "parser_calls": len(parsed_calls),
        "concurrent_workers": 8,
        "timings": report,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
