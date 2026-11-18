"""Worker agent: a bounded ReAct loop (Reason -> Act -> Observe) over a restricted toolset."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from core import config, repo
from core import timeparse as tp
from core.llm import LLMError
from tools import registry as R

PROTOCOL = """Respond with EXACTLY ONE JSON object per turn and nothing else.
To use a tool:   {"thought": "<short reasoning>", "action": "<tool name>", "args": {<arguments>}}
When finished:   {"final": "<message for the user, concise, markdown allowed>"}
Rules:
- Use only the listed tools. Never invent tool names, ids, emails or results.
- Dates are YYYY-MM-DD, times are 24h HH:MM. Resolve relative dates (tomorrow, next Friday) from today's date.
- If a tool returns status "pending_approval", the action is queued for the human: say so, do not retry it.
- If a tool fails, read the error, fix the arguments once, otherwise explain the problem honestly.
- Fill sensible defaults instead of asking questions, unless essential information is truly missing.
- Never claim an action succeeded unless a tool observation confirms it."""


@dataclass
class AgentSpec:
    name: str
    title: str
    description: str
    groups: list[str]
    instructions: str = ""
    max_steps: int = config.MAX_WORKER_STEPS


@dataclass
class AgentResult:
    agent: str
    task: str
    summary: str
    ok: bool = True
    tool_calls: list[dict] = field(default_factory=list)     # {tool, args, result}
    pending: list[dict] = field(default_factory=list)        # approvals queued by this agent


def build_system_prompt(spec: AgentSpec, ctx: R.ToolContext, memories: list[dict]) -> str:
    n = tp.now()
    tools = R.tools_for(spec.groups + ["memory"])
    mem = "\n".join(f"- ({m['kind']}) {m['content']}" for m in memories) or "(none)"
    return (
        f"[[ROLE:{spec.name}]]\n"
        f"You are the {spec.title} of a multi-agent productivity system. {spec.description}\n"
        f"{spec.instructions}\n\n"
        f"Today is {n.strftime('%A %Y-%m-%d')}, local time {n.strftime('%H:%M')}, timezone {config.TIMEZONE}. "
        f"The user is '{ctx.username}'.\n"
        f"Autonomy mode: {ctx.autonomy}.\n\n"
        f"Long-term memory about the user:\n{mem}\n\n"
        f"Tools:\n" + "\n".join(t.prompt_line() for t in tools) + "\n\n" + PROTOCOL
    )


def _trim(obj, limit: int = 3500) -> str:
    text = json.dumps(obj, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + '..."(truncated)"'


def run_agent(spec: AgentSpec, task: str, ctx: R.ToolContext, context_notes: str = "",
              memories: list[dict] | None = None) -> AgentResult:
    ctx.agent = spec.name
    tracer = ctx.tracer
    result = AgentResult(agent=spec.name, task=task, summary="")
    user_msg = f"Task: {task}"
    if context_notes:
        user_msg += f"\n\nContext from previous steps:\n{context_notes}"
    messages = [{"role": "system", "content": build_system_prompt(spec, ctx, memories or [])},
                {"role": "user", "content": user_msg}]
    seen: set[str] = set()
    for step in range(spec.max_steps):
        try:
            decision = ctx.llm.chat_json(messages, role=spec.name)
        except LLMError as exc:
            result.ok = False
            result.summary = f"⚠️ The language model is unavailable ({exc})."
            tracer and tracer.emit(spec.name, "error", str(exc))
            return result
        if not isinstance(decision, dict):
            result.summary = "I could not produce a structured answer. Please rephrase and try again."
            result.ok = False
            return result
        if "final" in decision and "action" not in decision:
            result.summary = str(decision["final"]).strip()
            tracer and tracer.emit(spec.name, "final", result.summary)
            return result
        action = decision.get("action")
        args = decision.get("args") or {}
        if not action:
            result.summary = str(decision.get("thought") or decision)[:1500]
            return result
        if decision.get("thought") and tracer:
            tracer.emit(spec.name, "thought", decision["thought"])
        signature = f"{action}:{json.dumps(args, sort_keys=True, default=str)}"
        if signature in seen:
            messages.append({"role": "assistant", "content": json.dumps(decision)})
            messages.append({"role": "user", "content": 'Observation: {"ok": false, "error": "Duplicate call. Use the previous observation and reply with {\\"final\\": ...}."}'})
            continue
        seen.add(signature)
        allowed = {t.name for t in R.tools_for(spec.groups + ["memory"])}
        if action not in allowed:
            obs = {"ok": False, "error": f"Tool '{action}' is not available to you. Allowed: {', '.join(sorted(allowed))}"}
        else:
            tracer and tracer.emit(spec.name, "tool_call", {"tool": action, "args": args})
            obs = R.execute(action, args, ctx)
        tracer and tracer.emit(spec.name, "observation", {"tool": action, "ok": obs.get("ok"),
                                                          "status": obs.get("status"), "message": obs.get("message") or obs.get("error")})
        result.tool_calls.append({"tool": action, "args": args, "result": obs})
        if obs.get("status") == "pending_approval":
            result.pending.append({"approval_id": obs["approval_id"], "tool": action, "message": obs["message"]})
        messages.append({"role": "assistant", "content": json.dumps(decision)})
        messages.append({"role": "user", "content": "Observation: " + _trim(obs)})
    # step budget exhausted -> ask for a wrap-up
    messages.append({"role": "user", "content": 'Step budget exhausted. Reply now with {"final": "..."} summarising what was done.'})
    try:
        decision = ctx.llm.chat_json(messages, role=spec.name)
        result.summary = str((decision or {}).get("final") or "Stopped after reaching the step limit.")
    except LLMError as exc:
        result.summary = f"Stopped after reaching the step limit ({exc})."
        result.ok = False
    return result
