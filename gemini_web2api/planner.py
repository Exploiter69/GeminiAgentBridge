"""Conservative, opt-in planner experiment for prompt-emulated tool calling."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


@dataclass(frozen=True)
class PlannerProposal:
    confidence: str
    reason: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None

    @property
    def should_synthesize(self) -> bool:
        return self.confidence == "high" and bool(self.tool_name)


def _functions(tool_defs):
    result = {}
    for tool in tool_defs or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name.strip():
            result[name.strip()] = fn
    return result


def _text(fn):
    return f"{fn.get('name', '')} {fn.get('description', '')}".lower()


def _schema_properties(fn):
    params = fn.get("parameters") or {}
    props = params.get("properties", {}) if isinstance(params, dict) else {}
    return props if isinstance(props, dict) else {}


def _required(fn):
    params = fn.get("parameters") or {}
    required = params.get("required", []) if isinstance(params, dict) else []
    return required if isinstance(required, list) else []


def _extract_explicit_path(request):
    """Return only a path/filename directly present in the user's request."""
    quoted = re.findall(r"(?:['\"])([^'\"]+)(?:['\"])", request)
    for value in quoted:
        if "/" in value or "\\" in value or "." in value:
            return value
    match = re.search(r"(?<!\w)([\w./-]+\.[A-Za-z0-9_+-]+)(?!\w)", request)
    return match.group(1) if match else None


def _extract_search_query(request):
    patterns = [
        r"(?:search|find|grep|look for)\s+(?:for\s+)?[\"']([^\"']+)[\"']",
        r"(?:search|find|grep|look for)\s+(?:for\s+)?(.+?)(?:\s+in\s+(?:the\s+)?(?:repo|repository|codebase)\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            if value:
                return value
    return None


def propose(request: str, tool_defs: list[dict] | None, *, grounding=None):
    """Produce a conservative proposal; never execute or invent a path.

    High confidence requires exactly one matching operation and every required
    argument must be directly evidenced by the request. Ambiguous, multi-step,
    or under-specified requests remain with Gemini.
    """
    request = (request or "").strip()
    if not request:
        return PlannerProposal("low", "empty request")
    funcs = _functions(tool_defs)
    if not funcs:
        return PlannerProposal("low", "no declared tools")
    lowered = request.lower()
    if re.search(r"\b(?:then|after that|and then|next)\b", lowered):
        return PlannerProposal("low", "multi-step request requires model planning")

    path, query = _extract_explicit_path(request), _extract_search_query(request)
    candidates = []
    for name, fn in funcs.items():
        desc = _text(fn)
        if any(w in desc for w in ("search", "grep", "find", "query")) and query:
            candidates.append((name, "search"))
        if any(w in desc for w in ("list", "directory", "files")) and re.search(r"\b(list|show)\b.*\bfiles?\b", lowered):
            candidates.append((name, "list"))
        if any(w in desc for w in ("read", "cat", "open")) and re.search(r"\b(read|cat|open)\b", lowered) and path:
            candidates.append((name, "read"))
        if any(w in desc for w in ("edit", "write", "modify", "update")) and re.search(r"\b(edit|write|modify|update)\b", lowered) and path:
            candidates.append((name, "edit"))

    if not candidates:
        return PlannerProposal("medium", "intent is not mapped to one evidence-backed tool")
    by_kind = {}
    for name, kind in candidates:
        by_kind.setdefault(kind, []).append(name)
    if len(by_kind) != 1:
        return PlannerProposal("medium", "request maps to multiple operation types")
    kind, names = next(iter(by_kind.items()))
    if len(names) != 1:
        return PlannerProposal("medium", "multiple tools match the same intent")

    name, fn, args = names[0], funcs[names[0]], {}
    props = _schema_properties(fn)
    if kind in {"read", "edit"}:
        if "path" not in props or not path:
            return PlannerProposal("medium", "required path is not directly evidenced")
        args["path"] = path
    elif kind == "search":
        query_key = "query" if "query" in props else "pattern" if "pattern" in props else None
        if not query_key or not query:
            return PlannerProposal("medium", "search argument is not directly evidenced")
        args[query_key] = query

    missing = [key for key in _required(fn) if key not in args]
    if missing:
        return PlannerProposal("medium", "required argument is not directly evidenced: " + ", ".join(missing))
    return PlannerProposal("high", "explicit request matches one evidence-backed tool", name, args)


def proposal_to_tool_call(proposal: PlannerProposal) -> str | None:
    """Serialize only a high-confidence proposal into the strict protocol."""
    if not proposal.should_synthesize:
        return None
    return "@@TOOL_CALL@@\n" + json.dumps(
        {"name": proposal.tool_name, "arguments": proposal.arguments or {}},
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n@@END_TOOL_CALL@@"
