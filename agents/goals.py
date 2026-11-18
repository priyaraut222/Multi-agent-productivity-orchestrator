"""Goal decomposition: goal -> milestones -> tasks, with validation, fallback template, and re-planning."""
from __future__ import annotations

from datetime import date, timedelta

from core import repo, scheduler
from core import timeparse as tp
from tools._util import ask_llm_json

SYSTEM = """You are a planning expert. Decompose the user's goal into a realistic plan.
Return ONLY JSON:
{"title": str, "summary": str,
 "milestones": [{"title": str, "due_in_days": int,
                 "tasks": [{"title": str, "description": str, "estimated_hours": number, "priority": "low|medium|high|urgent"}]}]}
Rules: 3-6 milestones in chronological order; 2-5 tasks each; tasks are concrete, <=6 hours each; the
total effort must fit the available hours per week; the last milestone due_in_days must be <= the horizon."""


def fallback_plan(goal: str, horizon_days: int, hours_per_week: float) -> dict:
    phases = [("Clarify scope & success criteria", ["Define what 'done' looks like", "List constraints and resources"]),
              ("Research & plan", ["Research approaches and examples", "Draft a step-by-step plan"]),
              ("Core execution", ["Complete the first working version", "Complete the main body of work"]),
              ("Review & improve", ["Get feedback or self-review", "Fix gaps and polish"]),
              ("Finish & reflect", ["Deliver / publish the result", "Write a short retrospective"])]
    per_task = max(0.5, min(4.0, round(hours_per_week / 3, 1)))
    out = []
    for i, (title, tasks) in enumerate(phases, start=1):
        out.append({"title": title, "due_in_days": max(1, round(horizon_days * i / len(phases))),
                    "tasks": [{"title": f"{t} — {goal}"[:110], "description": "", "estimated_hours": per_task,
                               "priority": "high" if i <= 2 else "medium"} for t in tasks]})
    return {"title": goal, "summary": "Template plan (offline mode). Connect a free LLM for a tailored plan.", "milestones": out}


def validate_plan(plan, horizon_days: int) -> dict | None:
    if not isinstance(plan, dict) or not isinstance(plan.get("milestones"), list) or not plan["milestones"]:
        return None
    clean = []
    for m in plan["milestones"][:8]:
        if not isinstance(m, dict) or not m.get("title"):
            continue
        tasks = []
        for t in (m.get("tasks") or [])[:6]:
            if isinstance(t, dict) and t.get("title"):
                try:
                    hrs = float(t.get("estimated_hours") or 1)
                except (TypeError, ValueError):
                    hrs = 1.0
                pr = str(t.get("priority", "medium")).lower()
                tasks.append({"title": str(t["title"])[:120], "description": str(t.get("description", ""))[:400],
                              "estimated_hours": max(0.25, min(hrs, 8.0)), "priority": pr if pr in repo.PRIORITIES else "medium"})
        if tasks:
            try:
                days = int(m.get("due_in_days") or 7)
            except (TypeError, ValueError):
                days = 7
            clean.append({"title": str(m["title"])[:120], "due_in_days": max(1, min(days, max(horizon_days, 1))), "tasks": tasks})
    if not clean:
        return None
    clean.sort(key=lambda m: m["due_in_days"])
    return {"title": str(plan.get("title") or "Goal")[:120], "summary": str(plan.get("summary") or ""), "milestones": clean}


def propose_plan(ctx, goal: str, target_date: str = "", hours_per_week: float = 6, extra: str = "") -> dict:
    today = tp.today()
    horizon = (date.fromisoformat(target_date) - today).days if target_date else 30
    horizon = max(horizon, 3)
    memories = "; ".join(m["content"] for m in repo.search_memories(ctx.user_id, goal, 4))
    raw = ask_llm_json(ctx, SYSTEM, f"Goal: {goal}\nHorizon: {horizon} days (target {target_date or 'flexible'})\n"
                       f"Available hours/week: {hours_per_week}\nMemories: {memories}\nExtra: {extra}", role="writer", max_tokens=2200)
    plan = validate_plan(raw, horizon) or fallback_plan(goal, horizon, float(hours_per_week))
    plan["title"] = plan.get("title") or goal
    plan["horizon_days"] = horizon
    plan["target_date"] = target_date or (today + timedelta(days=horizon)).isoformat()
    return plan


def commit_plan(user_id: int, plan: dict, description: str = "") -> int:
    today = tp.today()
    gid = repo.add_goal(user_id, plan["title"], description or plan.get("summary", ""), plan.get("target_date"))
    for m in plan["milestones"]:
        due = (today + timedelta(days=int(m["due_in_days"]))).isoformat()
        mid = repo.add_milestone(gid, m["title"], due)
        for t in m["tasks"]:
            repo.add_task(user_id, t["title"], description=t.get("description", ""), priority=t["priority"], due_date=due,
                          estimated_hours=t["estimated_hours"], goal_id=gid, milestone_id=mid, source="goal", kind="todo")
    return gid


def replan_goal(user_id: int, goal_id: int) -> list[dict]:
    """Adaptive re-planning: push overdue open tasks of a goal forward, keeping their priority order."""
    today = tp.today()
    moves, day = [], today
    late = [t for t in repo.list_tasks(user_id, open_only=True, goal_id=goal_id) if t.get("due_date") and t["due_date"] < today.isoformat()]
    for t in sorted(late, key=lambda x: -scheduler.score(x, today.isoformat())):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        repo.update_task(t["id"], user_id, due_date=day.isoformat())
        moves.append({"id": t["id"], "title": t["title"], "new_due": day.isoformat()})
        day += timedelta(days=1)
    return moves
