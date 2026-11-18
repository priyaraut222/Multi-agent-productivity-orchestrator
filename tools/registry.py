"""Tool registry with typed argument validation, risk levels and human-in-the-loop approval gating."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from core import repo

AUTONOMY_LEVELS = {
    "ask_all": "Ask before every change (safest)",
    "ask_external": "Ask only for external actions - emails, GitHub, invites (recommended)",
    "auto": "Fully autonomous (no confirmations)",
}


@dataclass
class ToolContext:
    user_id: int
    llm: Any = None                       # LLMRouter
    run_id: int | None = None
    agent: str = ""
    autonomy: str = "ask_external"
    username: str = ""
    tracer: Any = None


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, dict]               # {"title": {"type": "string", "description": "...", "required": True}}
    func: Callable[..., dict]
    group: str
    risk: str | Callable[[dict], str] = "read"   # read | write | external
    summarize: Callable[[dict], str] | None = None

    def risk_for(self, args: dict) -> str:
        return self.risk(args) if callable(self.risk) else self.risk

    def signature(self) -> str:
        parts = []
        for k, v in self.params.items():
            parts.append(f"{k}{'*' if v.get('required') else ''}: {v.get('type', 'string')}")
        return f"{self.name}({', '.join(parts)})"

    def prompt_line(self) -> str:
        hints = "; ".join(f"{k}={v['description']}" for k, v in self.params.items() if v.get("description"))
        return f"- {self.signature()} — {self.description}" + (f" [{hints}]" if hints else "")


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    REGISTRY[tool.name] = tool
    return tool


def tools_for(groups: list[str]) -> list[Tool]:
    return [t for t in REGISTRY.values() if t.group in groups]


def _coerce(value: Any, typ: str):
    if value is None:
        return None
    try:
        if typ == "integer":
            return int(float(value))
        if typ == "number":
            return float(value)
        if typ == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "y")
        if typ == "array" and isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if typ == "object" and isinstance(value, str):
            return json.loads(value)
        if typ == "string":
            return value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    except (ValueError, TypeError):
        raise ValueError(f"cannot convert {value!r} to {typ}")
    return value


def validate_args(tool: Tool, args: dict) -> dict:
    """Drop unknown args, coerce types, enforce required ones."""
    clean = {}
    for k, spec in tool.params.items():
        if k in args and args[k] not in (None, ""):
            clean[k] = _coerce(args[k], spec.get("type", "string"))
        elif spec.get("required"):
            raise ValueError(f"missing required argument '{k}'")
    return clean


def needs_approval(tool: Tool, args: dict, autonomy: str) -> bool:
    risk = tool.risk_for(args)
    if risk == "read" or autonomy == "auto":
        return False
    if risk == "external":
        return True
    return autonomy == "ask_all"          # local write


def describe(tool: Tool, args: dict) -> str:
    if tool.summarize:
        try:
            return tool.summarize(args)
        except Exception:
            pass
    short = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
    return f"{tool.name}({short})"


def execute(name: str, args: dict, ctx: ToolContext, force: bool = False) -> dict:
    """Run a tool. External/risky calls are queued for approval unless ``force`` (user already approved)."""
    tool = REGISTRY.get(name)
    if not tool:
        return {"ok": False, "error": f"Unknown tool '{name}'. Available: {', '.join(sorted(REGISTRY))}"}
    try:
        clean = validate_args(tool, args or {})
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "usage": tool.signature()}
    if not force and needs_approval(tool, clean, ctx.autonomy):
        summary = describe(tool, clean)
        approval_id = repo.create_approval(ctx.user_id, name, clean, summary, ctx.agent, ctx.run_id)
        return {"ok": True, "status": "pending_approval", "approval_id": approval_id,
                "message": f"⏳ Queued for your approval: {summary}"}
    try:
        result = tool.func(ctx, **clean)
    except Exception as exc:  # tools must never crash the agent loop
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(result, dict):
        result = {"result": result}
    result.setdefault("ok", True)
    return result


def run_approved(approval_id: int, user_id: int, llm=None) -> dict:
    """Execute a previously queued action after the human approved it."""
    appr = repo.get_approval(approval_id, user_id)
    if not appr or appr["status"] != "pending":
        return {"ok": False, "error": "Approval not found or already resolved."}
    ctx = ToolContext(user_id=user_id, llm=llm, run_id=appr["run_id"], agent=appr["agent"] or "", autonomy="auto")
    result = execute(appr["tool"], appr["args"], ctx, force=True)
    repo.resolve_approval(approval_id, "executed" if result.get("ok") else "failed", result)
    return result


def reject(approval_id: int, user_id: int) -> None:
    appr = repo.get_approval(approval_id, user_id)
    if appr and appr["status"] == "pending":
        repo.resolve_approval(approval_id, "rejected", {"ok": False, "message": "Rejected by user"})
