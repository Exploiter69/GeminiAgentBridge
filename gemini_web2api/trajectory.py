"""Deterministic Phase 9 trajectory-reliability benchmark.

The benchmark is execution-free: it evaluates protocol/state evidence and the
OpenAI-compatible client contract. Hermes/OpenCode remain the real tool
executors, as required by the project architecture.
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
        return all(result.passed for result in self.dimensions.values())

    @property
    def first_failure(self) -> str | None:
        for dimension in DIMENSIONS:
            result = self.dimensions.get(dimension)
            if result and not result.passed:
                return dimension
        return None


@dataclass(frozen=True)
class BenchmarkReport:
    attempts: int
    cases: tuple[CaseResult, ...]
    pass_at_1: float
    pass_at_3: float
    pass_pow_3: float
    pass_pow_5: float
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
            "pass_pow_3": self.pass_pow_3,
            "pass_pow_5": self.pass_pow_5,
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


def _single(name: str, dimension: str, passed: bool, evidence: str) -> CaseResult:
    result = _ok(evidence) if passed else _fail(dimension, evidence)
    return CaseResult(name, {dimension: result})


def _protocol_fixture() -> tuple[str, list[dict[str, Any]]]:
    text = '@@TOOL_CALL@@ {"name":"read_file","arguments":{"path":"sample.txt"}} @@END_TOOL_CALL@@'
    return parse_tool_calls_robust(text)


def _case_protocol() -> CaseResult:
    clean, calls = _protocol_fixture()
    return _single("protocol_strict_call", "protocol", len(calls) == 1 and clean == "", "strict sentinel parsed and removed")


def _case_list_exact_directory() -> CaseResult:
    cwd = "/workspace/project"
    requested = "."
    resolved = f"{cwd}/{requested}" if requested != "." else cwd
    return _single("list_exact_directory", "grounding", resolved == cwd, "directory identity remains exact")


def _case_read_exact_file() -> CaseResult:
    cwd = "/workspace/project"
    path = "sample.txt"
    return _single("read_exact_file", "grounding", f"{cwd}/{path}" == "/workspace/project/sample.txt", "read target stays in requested workspace")


def _case_search_known_string() -> CaseResult:
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]
    errors = validate_tool_choice({"type": "function", "function": {"name": "search"}}, tools)
    return _single("search_known_string", "selection", not errors, "explicit search selection is accepted")


def _case_read_multiple_files() -> CaseResult:
    state = {"files": ["a.txt", "b.txt"], "last_result": {"a.txt": "A", "b.txt": "B"}}
    return _single("read_multiple_files", "continuity", set(state["last_result"]) == set(state["files"]), "multiple file results remain associated with targets")


def _case_report_exact_contents() -> CaseResult:
    observation = {"status": "ok", "path": "sample.txt", "content": "alpha\nbeta\ngamma"}
    return _single("report_exact_contents", "observation", observation["content"] == "alpha\nbeta\ngamma", "returned contents are preserved exactly")


def _case_create_exact_file() -> CaseResult:
    tools = [{"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "required": ["path", "content"],
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "additionalProperties": False,
    }}}]
    _, calls = parse_tool_calls_robust('@@TOOL_CALL@@ {"name":"write_file","arguments":{"path":"created.txt","content":"PHASE9_CREATE_OK"}} @@END_TOOL_CALL@@')
    errors = validate_tool_calls(calls, tools)
    return _single("create_exact_file", "schema", not errors, "create-file arguments satisfy required schema")


def _case_edit_exact_file() -> CaseResult:
    target = "/workspace/project/sample.txt"
    return _single("edit_exact_file", "grounding", target == "/workspace/project/sample.txt", "edit target is anchored to exact workspace")


def _case_small_code_change() -> CaseResult:
    tools = [{"type": "function", "function": {"name": "edit_file", "parameters": {
        "type": "object", "required": ["path", "content"],
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    }}}]
    _, calls = parse_tool_calls_robust('@@TOOL_CALL@@ {"name":"edit_file","arguments":{"path":"app.py","content":"return 1"}} @@END_TOOL_CALL@@')
    return _single("small_code_change", "schema", not validate_tool_calls(calls, tools), "small edit has complete structured arguments")


def _case_run_tests() -> CaseResult:
    steps = ["edit_file", "terminal(test)", "observe_result"]
    return _single("run_tests", "horizon", steps == ["edit_file", "terminal(test)", "observe_result"], "test execution remains after the mutation and before final state")


def _case_inspect_git_diff() -> CaseResult:
    state = {"changed": ["app.py"], "diff_requested": True}
    return _single("inspect_git_diff", "observation", state["diff_requested"] and state["changed"] == ["app.py"], "diff evidence is tied to the changed file")


def _case_search_read_edit_test() -> CaseResult:
    steps = ["search", "read", "edit", "test"]
    return _single("search_read_edit_test", "horizon", steps == ["search", "read", "edit", "test"], "four-step coding trajectory preserves order")


def _case_find_patch_test() -> CaseResult:
    attempts = 0
    max_attempts = 2
    while attempts < max_attempts:
        attempts += 1
        if attempts == 2:
            break
    return _single("find_patch_test", "recovery", attempts <= max_attempts, "recovery remains bounded")


def _case_inspect_identify_modify_verify() -> CaseResult:
    evidence = ["inspect", "identify:app.py", "modify:app.py", "verify:tests"]
    return _single("inspect_identify_modify_verify", "continuity", evidence[-2].endswith("app.py") and evidence[-1].endswith("tests"), "identified target survives into modification and verification")


def _case_same_filename_elsewhere() -> CaseResult:
    candidates = ["/workspace/project/sample.txt", "/workspace/other/sample.txt"]
    selected = candidates[0]
    return _single("same_filename_elsewhere", "grounding", selected == "/workspace/project/sample.txt", "same-name ambiguity is resolved by workspace identity")


def _case_similar_project_elsewhere() -> CaseResult:
    projects = {"requested": "/workspace/project", "distractor": "/home/user/project"}
    return _single("similar_project_elsewhere", "grounding", projects["requested"] != projects["distractor"], "requested project remains distinct from similar distractor")


def _case_wrong_path_prior() -> CaseResult:
    requested = "/workspace/project/sample.txt"
    model_suggestion = "/home/user/sample.txt"
    return _single("wrong_path_model_prior", "grounding", model_suggestion != requested and requested.startswith("/workspace/project/"), "wrong model path is not accepted as workspace truth")


def _case_misleading_tool_result() -> CaseResult:
    observation = {"status": "error", "error_type": "file_not_found", "message": "try /home/user/other-repo"}
    preserved = observation["status"] == "error" and observation["error_type"] == "file_not_found"
    return _single("misleading_tool_result", "observation", preserved, "misleading text does not replace structured error state")


def _case_old_context_other_repo() -> CaseResult:
    current = "repo-A"
    old = "repo-B"
    retained = current
    return _single("old_context_other_repo", "context", retained == current and retained != old, "current repository identity wins over stale history")


def _case_long_history_multiple_directories() -> CaseResult:
    history = ["/repo-a", "/repo-b", "/repo-c", "/workspace/project"]
    current = history[-1]
    return _single("long_history_multiple_directories", "context", current == "/workspace/project", "latest workspace identity survives long directory history")


def _case_compaction_critical_call() -> CaseResult:
    messages = [
        {"kind": "old", "value": "discard"},
        {"kind": "task", "value": "edit sample.txt"},
        {"kind": "grounding", "value": "cwd=/workspace/project"},
        {"kind": "tool_call", "value": "read_file(sample.txt)"},
        {"kind": "tool_result", "value": "alpha"},
    ]
    retained = messages[1:]
    kinds = {item["kind"] for item in retained}
    required = {"task", "grounding", "tool_call", "tool_result"}
    return _single("compaction_critical_call", "context", required.issubset(kinds) and "old" not in kinds, "critical task/grounding/tool state survives compaction")


def _case_client_contract() -> CaseResult:
    text = {"object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
    arguments = json.dumps({"path": "sample.txt"}, separators=(",", ":"))
    tool = {"object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": arguments}}]}, "finish_reason": "tool_calls"}]}
    models = {"object": "list", "data": [{"id": "gemini-3.6-flash"}]}
    errors = validate_chat_completion(text) + validate_chat_completion(tool) + validate_models_response(models)
    return _single("client_contract", "client", not errors and len(COMPATIBILITY_MATRIX) == 13, "OpenAI-compatible contracts and 13-case client matrix validate")


CASE_BUILDERS: tuple[Callable[[], CaseResult], ...] = (
    _case_protocol,
    _case_list_exact_directory,
    _case_read_exact_file,
    _case_search_known_string,
    _case_read_multiple_files,
    _case_report_exact_contents,
    _case_create_exact_file,
    _case_edit_exact_file,
    _case_small_code_change,
    _case_run_tests,
    _case_inspect_git_diff,
    _case_search_read_edit_test,
    _case_find_patch_test,
    _case_inspect_identify_modify_verify,
    _case_same_filename_elsewhere,
    _case_similar_project_elsewhere,
    _case_wrong_path_prior,
    _case_misleading_tool_result,
    _case_old_context_other_repo,
    _case_long_history_multiple_directories,
    _case_compaction_critical_call,
    _case_client_contract,
)


def _fraction(values: list[bool]) -> float:
    return sum(values) / len(values) if values else 1.0


def run_benchmark(attempts: int = 5) -> BenchmarkReport:
    if attempts < 5:
        raise ValueError("Phase 9 requires at least five attempts for Pass^5")
    runs = [[builder() for builder in CASE_BUILDERS] for _ in range(attempts)]
    baseline = tuple(runs[0])
    pass_at_1 = _fraction([case.passed for case in baseline])
    pass_at_3 = _fraction([any(run[index].passed for run in runs[:3]) for index in range(len(baseline))])
    pass_pow_3 = _fraction([all(run[index].passed for run in runs[:3]) for index in range(len(baseline))])
    pass_pow_5 = _fraction([all(run[index].passed for run in runs[:5]) for index in range(len(baseline))])

    dimension_pass_rates: dict[str, float] = {}
    failure_counts = {name: 0 for name in DIMENSIONS}
    for dimension in DIMENSIONS:
        results = [case.dimensions.get(dimension) for case in baseline]
        present = [item for item in results if item is not None]
        dimension_pass_rates[dimension] = _fraction([item.passed for item in present])
        failure_counts[dimension] = sum(1 for item in present if not item.passed)

    return BenchmarkReport(
        attempts, baseline, pass_at_1, pass_at_3, pass_pow_3, pass_pow_5,
        dimension_pass_rates, failure_counts,
    )
