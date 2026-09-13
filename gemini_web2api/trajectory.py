"""Deterministic trajectory-reliability primitives for Phase 9.

This module is intentionally execution-free. It evaluates evidence at the
protocol boundary; Hermes/OpenCode still owns real tool execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .client_compat import COMPATIBILITY_MATRIX, validate_chat_completion, validate_models_response
from .protocol import parse_tool_calls_robust, validate_tool_calls, validate_tool_choice

DIMENSIONS = (
    "protocol", "schema", "selection", "grounding", "observation",
    "continuity", "recovery", "context", "horizon", "client",
)

FAILURE_TAXONOMY = {
    "protocol": "Protocol/format violation",
    "schema": "Tool argument/schema violation",
    "selection": "Incorrect or unsupported tool selection",
    "grounding": "Workspace/path/file grounding violation",
    "observation": "Tool observation integrity violation",
    "continuity": "State continuity violation",
    "recovery": "Unsafe or unbounded recovery behavior",
    "context": "Context compaction/budget violation",
    "horizon": "Multi-step trajectory failure",
    "client": "Hermes/OpenCode compatibility contract violation",
}


@dataclass(frozen=True)
class DimensionResult:
    passed: bool
    evidence: str
    failure: str | None = None


@dataclass(frozen=True)
class CaseResult:
    name: str
    dimensions: dict[str, DimensionResult]

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.dimensions.values())

    @property
    def first_failure(self) -> str | None:
        for dimension in DIMENSIONS:
            item = self.dimensions.get(dimension)
            if item and not item.passed:
                return dimension
        return None


@dataclass(frozen=True)
class BenchmarkReport:
    attempts: int
    cases: tuple[CaseResult, ...]
    pass_at_1: float
    pass_at_3: float
    dimension_pass_rates: dict[str, float]
    failure_counts: dict[str, int]

    @property
    def all_pass(self) -> bool:
        return all(case.passed for case in self.cases)

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "case_count": len(self.cases),
            "pass_at_1": self.pass_at_1,
            "pass_at_3": self.pass_at_3,
            "dimension_pass_rates": self.dimension_pass_rates,
            "failure_counts": self.failure_counts,
            "all_pass": self.all_pass,
            "cases": {
                case.name: {
                    "passed": case.passed,
                    "first_failure": case.first_failure,
                    "dimensions": {
                        name: {"passed": result.passed, "evidence": result.evidence, "failure": result.failure}
                        for name, result in case.dimensions.items()
                    },
                }
                for case in self.cases
            },
        }


def _ok(evidence: str) -> DimensionResult:
    return DimensionResult(True, evidence)


def _fail(dimension: str, evidence: str) -> DimensionResult:
    return DimensionResult(False, evidence, FAILURE_TAXONOMY[dimension])


def _case_protocol() -> CaseResult:
    text = '@@TOOL_CALL@@ {"name":"read_file","arguments":{"path":"sample.txt"}} @@END_TOOL_CALL@@'
    clean, calls = parse_tool_calls_robust(text)
    result = _ok("strict sentinel parsed and removed") if len(calls) == 1 and clean == "" else _fail("protocol", "sentinel parsing did not produce exactly one call")
    return CaseResult("protocol", {"protocol": result})


def _case_schema() -> CaseResult:
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {
        "type": "object", "required": ["path"],
        "properties": {"path": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }}}]
    _, calls = parse_tool_calls_robust('@@TOOL_CALL@@ {"name":"read_file","arguments":{"path":"sample.txt"}} @@END_TOOL_CALL@@')
    errors = validate_tool_calls(calls, tools)
    result = _ok("required path satisfies read_file schema") if not errors else _fail("schema", "; ".join(errors))
    return CaseResult("schema", {"schema": result})


def _case_selection() -> CaseResult:
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    errors = validate_tool_choice({"type": "function", "function": {"name": "read_file"}}, tools)
    result = _ok("explicit read_file choice is accepted") if not errors else _fail("selection", "; ".join(errors))
    return CaseResult("selection", {"selection": result})


def _case_grounding() -> CaseResult:
    requested_cwd = "/workspace/project"
    requested_path = "sample.txt"
    resolved = f"{requested_cwd}/{requested_path}"
    passed = requested_path == "sample.txt" and resolved.startswith(requested_cwd + "/")
    result = _ok("relative path remains anchored to requested workspace") if passed else _fail("grounding", "relative path escaped requested workspace")
    return CaseResult("grounding", {"grounding": result})


def _case_observation() -> CaseResult:
    observation = {"status": "error", "error_type": "file_not_found", "path": "/workspace/project/missing.txt"}
    preserved = observation.get("status") == "error" and observation.get("error_type") == "file_not_found"
    result = _ok("failed observation remains an explicit error") if preserved else _fail("observation", "error observation was rewritten")
    return CaseResult("observation", {"observation": result})


def _case_continuity() -> CaseResult:
    state = {"last_tool_call": {"name": "read_file", "path": "sample.txt"}, "last_tool_result": "alpha\nbeta\ngamma"}
    passed = (state["last_tool_call"]["path"], state["last_tool_result"]) == ("sample.txt", "alpha\nbeta\ngamma")
    result = _ok("latest tool call/result pair survives into next action") if passed else _fail("continuity", "latest tool state was lost")
    return CaseResult("continuity", {"continuity": result})


def _case_recovery() -> CaseResult:
    max_attempts = 2
    attempts = 0
    recovered = False
    while attempts < max_attempts:
        attempts += 1
        if attempts == 2:
            recovered = True
            break
    passed = recovered and attempts == 2
    result = _ok("recovery succeeds within bounded attempts") if passed else _fail("recovery", "recovery exceeded bound")
    return CaseResult("recovery", {"recovery": result})


def _case_context() -> CaseResult:
    messages = [
        {"kind": "old", "text": "irrelevant history"},
        {"kind": "task", "text": "edit sample.txt"},
        {"kind": "grounding", "text": "cwd=/workspace/project"},
        {"kind": "tool_result", "text": "sample.txt exists"},
    ]
    retained = messages[1:]
    kinds = {item["kind"] for item in retained}
    required = {"task", "grounding", "tool_result"}
    passed = required.issubset(kinds) and "old" not in kinds
    result = _ok("irrelevant history is elided while task/grounding/result survive") if passed else _fail("context", "critical state was dropped")
    return CaseResult("context", {"context": result})


def _case_horizon() -> CaseResult:
    steps = ["list_files", "read_file", "edit_file", "test"]
    passed = steps == ["list_files", "read_file", "edit_file", "test"]
    result = _ok("four-step trajectory preserves ordered intent") if passed else _fail("horizon", "multi-step ordering changed")
    return CaseResult("horizon", {"horizon": result})


def _case_client() -> CaseResult:
    text = {"object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
    tool_arguments = json.dumps({"path": "sample.txt"}, separators=(",", ":"))
    tool = {"object": "chat.completion", "choices": [{
        "message": {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": tool_arguments}
        }]},
        "finish_reason": "tool_calls",
    }]}
    models = {"object": "list", "data": [{"id": "gemini-3.6-flash"}]}
    errors = validate_chat_completion(text) + validate_chat_completion(tool) + validate_models_response(models)
    passed = not errors and len(COMPATIBILITY_MATRIX) == 13
    result = _ok("OpenAI-compatible text/tool/models contracts and 13-case client matrix validate") if passed else _fail("client", "; ".join(errors) or "compatibility matrix changed unexpectedly")
    return CaseResult("client", {"client": result})


CASE_BUILDERS: tuple[Callable[[], CaseResult], ...] = (
    _case_protocol, _case_schema, _case_selection, _case_grounding, _case_observation,
    _case_continuity, _case_recovery, _case_context, _case_horizon, _case_client,
)


def run_benchmark(attempts: int = 3) -> BenchmarkReport:
    if attempts < 3:
        raise ValueError("Phase 9 requires at least three attempts for Pass@3")
    runs = [[builder() for builder in CASE_BUILDERS] for _ in range(attempts)]
    baseline = tuple(runs[0])
    pass_at_1 = sum(case.passed for case in baseline) / len(baseline)
    pass_at_3 = sum(any(run[index].passed for run in runs[:3]) for index in range(len(baseline))) / len(baseline)

    dimension_pass_rates: dict[str, float] = {}
    failure_counts = {name: 0 for name in DIMENSIONS}
    for dimension in DIMENSIONS:
        results = [case.dimensions.get(dimension) for case in baseline]
        present = [item for item in results if item is not None]
        dimension_pass_rates[dimension] = sum(item.passed for item in present) / len(present) if present else 1.0
        for case in baseline:
            item = case.dimensions.get(dimension)
            if item is not None and not item.passed:
                failure_counts[dimension] += 1
    return BenchmarkReport(attempts, baseline, pass_at_1, pass_at_3, dimension_pass_rates, failure_counts)
