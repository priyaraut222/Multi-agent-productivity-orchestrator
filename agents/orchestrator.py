"""Supervisor graph: recall -> supervise(route) -> execute workers (loop) -> critic -> (revise) -> finalize."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agents.base import AgentResult, run_agent
from agents.graph import END, StateGraph
from agents.specialists import DESCRIPTIONS, SPECIALISTS
from agents.tracing import Tracer
from core import config, repo
from core import timeparse as tp
from core.llm import LLMError, LLMRouter, make_llm
from tools import loader
from tools.registry import ToolContext

loader.load()

MEMORY_TRIGGER = re.compile(r"\b(remember|from now on|always|never|i prefer|i like to|i usually|my (favorite|favourite)|i('m| am) (a|an|working|studying))\b", re.I)
WRITE_CLAIM = re.compile(r"\bI(?:'ve| have|'ve just| just)?\s+(?:now\s+)?(created|scheduled|sent|added|deleted|updated|completed|marked|booked|opened|closed|moved)\b", re.I)
FAILURE_ADMIT = re.compile(r"couldn't|could not|can't|cannot|failed|unable|error|not connected|conflict|queued|approval|pending", re.I)

SUPERVISOR_PROMPT = """[[ROLE:supervisor]]
You are the Supervisor of a multi-agent productivity system. Decide which specialist agents must work on the user's request.

Specialists:
{agents}

Return ONLY JSON: {{"steps": [{{"agent": "<name>", "task": "<self-contained instruction for that agent>"}}], "direct_answer": null}}
- Use 1-{max_steps} steps, in the order they must run. A later step may use earlier results, so write tasks that reference what is needed.
- Resolve pronouns and relative dates yourself so each task is self-contained.
- For greetings, thanks or general chat that needs no tool, return {{"steps": [], "direct_answer": "<short reply>"}}.
Today is {today}. Memory about the user: {memory}"""

CRITIC_PROMPT = """[[ROLE:critic]]
You are a strict QA reviewer for an AI assistant. Compare the DRAFT answer against the user's REQUEST and the tool EVIDENCE.
Return ONLY JSON: {{"verdict": "pass" | "revise", "issues": [str], "feedback": "<what to fix>"}}
Fail the draft if it claims something the evidence does not show, ignores part of the request, or hides an error."""

SYNTH_PROMPT = """[[ROLE:synthesizer]]
You write the final reply to the user from the agents' step results. Be concise, friendly and concrete.
Keep links and ids. Mention anything queued for approval and any failure honestly. Do not invent facts."""


@dataclass
class RunResult:
    run_id: int | None
    answer: str
    steps: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    plan: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    revised: bool = False
    path: list[str] = field(default_factory=list)


def _evidence(results: list[AgentResult]) -> str:
    lines = []
    for r in results:
        for c in r.tool_calls:
            res = c["result"]
            lines.append(f"[{r.agent}] {c['tool']} -> ok={res.get('ok')} status={res.get('status')} "
                         f"msg={str(res.get('message') or res.get('error'))[:200]}")
    return "\n".join(lines) or "(no tool calls)"


def grounding_issues(answer: str, results: list[AgentResult]) -> list[str]:
    """Deterministic checks: claims must be backed by evidence, failures must be disclosed."""
    issues = []
    calls = [c for r in results for c in r.tool_calls]
    ok_writes = [c for c in calls if c["result"].get("ok") and c["result"].get("status") != "pending_approval"
                 and not c["tool"].startswith(("list_", "get_", "read_", "search_", "find_", "check_", "fetch_", "recall", "summarize_", "triage_", "draft_", "generate_daily", "weekly", "github_is"))]
    pending = [c for c in calls if c["result"].get("status") == "pending_approval"]
    failed = [c for c in calls if c["result"].get("ok") is False]
    if WRITE_CLAIM.search(answer) and not ok_writes and not pending:
        issues.append("The answer claims an action was completed but no tool call supports it.")
    if failed and not FAILURE_ADMIT.search(answer) and not ok_writes:
        issues.append("A tool call failed but the answer does not mention the problem: " + str(failed[0]["result"].get("error"))[:150])
    return issues


def build_graph(llm: LLMRouter, ctx: ToolContext, tracer: Tracer, fast: bool = False) -> StateGraph:
    g = StateGraph("supervisor")

    def recall(state):
        mems = repo.search_memories(ctx.user_id, state["query"], 5)
        tracer.emit("memory", "recall", [m["content"] for m in mems])
        return {"memories": mems}

    def supervise(state):
        prompt = SUPERVISOR_PROMPT.format(agents="\n".join(f"- {k}: {v}" for k, v in DESCRIPTIONS.items()),
                                          max_steps=config.MAX_PLAN_STEPS, today=tp.now().strftime("%A %Y-%m-%d %H:%M"),
                                          memory="; ".join(m["content"] for m in state["memories"]) or "none")
        history = state.get("history") or []
        msgs = [{"role": "system", "content": prompt}] + history[-6:] + [{"role": "user", "content": f"Task: {state['query']}"}]
        try:
            plan = llm.chat_json(msgs, role="supervisor")
        except LLMError as exc:
            tracer.emit("supervisor", "error", str(exc))
            return {"plan": [], "direct": f"⚠️ I couldn't reach any language model right now ({exc}). Check your API keys in Settings, or switch to Offline demo mode."}
        steps, direct = [], None
        if isinstance(plan, dict):
            direct = plan.get("direct_answer")
            for s in (plan.get("steps") or [])[: config.MAX_PLAN_STEPS]:
                if isinstance(s, dict) and s.get("agent") in SPECIALISTS and s.get("task"):
                    steps.append({"agent": s["agent"], "task": str(s["task"])})
        if not steps and not direct:
            steps = [{"agent": "tasks", "task": state["query"]}]     # safe default instead of failing
        tracer.emit("supervisor", "route", {"steps": steps, "direct_answer": bool(direct)})
        return {"plan": steps, "cursor": 0, "direct": direct, "results": []}

    def route_after_supervise(state):
        return "finalize" if state.get("direct") or not state["plan"] else "execute"

    def execute(state):
        step = state["plan"][state["cursor"]]
        notes = "\n".join(f"- {r.agent}: {r.summary}" for r in state["results"])
        tracer.emit(step["agent"], "start", step["task"])
        res = run_agent(SPECIALISTS[step["agent"]], step["task"], ctx, notes, state["memories"])
        results = state["results"] + [res]
        return {"results": results, "cursor": state["cursor"] + 1}

    def route_after_execute(state):
        return "execute" if state["cursor"] < len(state["plan"]) else "critic"

    def draft_answer(state, feedback: str = "") -> str:
        results: list[AgentResult] = state["results"]
        if len(results) == 1 and not feedback:
            return results[0].summary
        body = "\n\n".join(f"[{r.agent}] {r.summary}" for r in results)
        user = f"USER REQUEST: {state['query']}\n\nSTEP RESULTS:\n{body}" + (f"\n\nREVIEWER FEEDBACK TO ADDRESS: {feedback}" if feedback else "")
        try:
            return llm.chat([{"role": "system", "content": SYNTH_PROMPT}, {"role": "user", "content": user}],
                            role="synthesizer", max_tokens=900).strip()
        except LLMError:
            return body

    def critic(state):
        results: list[AgentResult] = state["results"]
        draft = draft_answer(state)
        issues = grounding_issues(draft, results)
        feedback = " ".join(issues)
        if not issues and not fast and not llm.is_offline and any(r.tool_calls for r in results):
            try:
                verdict = llm.chat_json([{"role": "system", "content": CRITIC_PROMPT},
                                         {"role": "user", "content": f"REQUEST: {state['query']}\n\nEVIDENCE:\n{_evidence(results)}\n\nDRAFT:\n{draft}"}],
                                        role="critic", max_tokens=400)
                if isinstance(verdict, dict) and verdict.get("verdict") == "revise":
                    issues = [str(i) for i in verdict.get("issues", [])] or ["Reviewer asked for a revision."]
                    feedback = str(verdict.get("feedback") or " ".join(issues))
            except LLMError:
                pass
        tracer.emit("critic", "verdict", {"verdict": "revise" if issues else "pass", "issues": issues})
        return {"draft": draft, "issues": issues, "feedback": feedback}

    def route_after_critic(state):
        return "revise" if state["issues"] and not state.get("revised") else "finalize"

    def revise(state):
        tracer.emit("synthesizer", "revise", state["feedback"])
        return {"draft": draft_answer(state, state["feedback"]), "revised": True, "issues": []}

    def finalize(state):
        answer = state.get("direct") or state.get("draft") or "Done."
        pending = [p for r in state.get("results", []) for p in r.pending]
        if pending and "approval" not in answer.lower():
            answer += "\n\n⏳ **Waiting for your approval:**\n" + "\n".join(f"- {p['message'].replace('⏳ Queued for your approval: ', '')}" for p in pending)
        if MEMORY_TRIGGER.search(state["query"]):
            repo.add_memory(ctx.user_id, state["query"].strip()[:300], "preference", 3)
            tracer.emit("memory", "write", state["query"][:120])
        tracer.emit("supervisor", "final", answer)
        return {"answer": answer, "pending": pending}

    for name, fn in [("recall", recall), ("supervise", supervise), ("execute", execute), ("critic", critic),
                     ("revise", revise), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.set_entry("recall")
    g.add_edge("recall", "supervise")
    g.add_conditional_edges("supervise", route_after_supervise, ["execute", "finalize"])
    g.add_conditional_edges("execute", route_after_execute, ["execute", "critic"])
    g.add_conditional_edges("critic", route_after_critic, ["revise", "finalize"])
    g.add_edge("revise", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def run(user_id: int, query: str, history: list[dict] | None = None, on_event=None, fast: bool = False,
        llm: LLMRouter | None = None, persist: bool = True) -> RunResult:
    user = repo.get_user(user_id) or {"username": "user"}
    llm = llm or make_llm(user_id)
    tracer = Tracer(user_id, query, on_event, persist)
    autonomy = repo.get_setting(user_id, "autonomy", "ask_external")
    ctx = ToolContext(user_id=user_id, llm=llm, run_id=tracer.run_id, autonomy=autonomy, username=user["username"], tracer=tracer)
    graph = build_graph(llm, ctx, tracer, fast)
    state = {"query": query, "history": history or []}
    try:
        state = graph.run(state)
        status = "ok"
    except Exception as exc:  # last-resort guard: a run must always end with a message
        tracer.emit("system", "error", f"{type(exc).__name__}: {exc}")
        state.update({"answer": f"⚠️ Something went wrong while processing your request: {exc}", "pending": []})
        status = "error"
    tracer.finish(status, state.get("answer", ""), llm.calls)
    return RunResult(run_id=tracer.run_id, answer=state.get("answer", ""), steps=tracer.events, pending=state.get("pending", []),
                     plan=state.get("plan", []), llm_calls=llm.calls, revised=bool(state.get("revised")), path=state.get("_path", []))
