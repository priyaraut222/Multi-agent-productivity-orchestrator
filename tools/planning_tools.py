"""Planner & goal tools (wrap the planning engine so agents can call them)."""
from __future__ import annotations

from agents import goals, insights, planner
from core import repo
from core import timeparse as tp
from tools._util import fail
from tools.registry import Tool, ToolContext, register

P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731


def generate_daily_plan(ctx: ToolContext, date: str = "", work_start: str = "", work_end: str = "") -> dict:
    plan = planner.generate_plan(ctx, date or None, work_start or None, work_end or None)
    return {"plan": plan, "slots": [{"title": f"{s['start']}-{s['end']} {s['title']}"} for s in plan["slots"]],
            "plan_summary": planner.plan_summary(plan), "message": f"🗓️ Plan for {plan['date']} generated (overlap-free). Say 'apply my plan' to put it on the calendar."}


def apply_daily_plan(ctx: ToolContext, date: str = "") -> dict:
    date = date or tp.today().isoformat()
    plan = repo.get_plan(ctx.user_id, date)
    if not plan:
        return fail("No plan exists for that date yet. Generate one first.")
    n = planner.apply_plan(ctx.user_id, plan)
    return {"message": f"✅ Applied plan: {n} focus block(s) added to your calendar and tasks."}


def reschedule_overdue(ctx: ToolContext) -> dict:
    moves = planner.reschedule_overdue(ctx.user_id)
    return {"moves": moves, "tasks": [{"title": f"{m['title']} → {m['new_due']}"} for m in moves],
            "message": f"♻️ Rescheduled {len(moves)} overdue task(s)." if moves else "No overdue tasks. 🎉"}


def create_goal_plan(ctx: ToolContext, goal: str, target_date: str = "", hours_per_week: float = 6, notes: str = "") -> dict:
    plan = goals.propose_plan(ctx, goal, target_date, float(hours_per_week or 6), notes)
    gid = goals.commit_plan(ctx.user_id, plan)
    total = sum(len(m["tasks"]) for m in plan["milestones"])
    lines = [f"🎯 Created goal #{gid} '{plan['title']}' with {len(plan['milestones'])} milestones and {total} tasks."]
    lines += [f"- {m['title']} (in {m['due_in_days']}d, {len(m['tasks'])} tasks)" for m in plan["milestones"]]
    return {"goal_id": gid, "plan": plan, "message": "\n".join(lines)}


def list_goals(ctx: ToolContext) -> dict:
    gs = repo.list_goals(ctx.user_id, "active")
    return {"goals": [{"title": f"{g['title']} — {int(g['progress'] * 100)}% ({g['done_tasks']}/{g['total_tasks']})"} for g in gs],
            "message": f"{len(gs)} active goal(s)."}


def replan_goal(ctx: ToolContext, goal_id: int) -> dict:
    if not repo.get_goal(int(goal_id), ctx.user_id):
        return fail("Goal not found.")
    moves = goals.replan_goal(ctx.user_id, int(goal_id))
    return {"moves": moves, "message": f"Re-planned {len(moves)} overdue task(s) of goal #{goal_id}."}


def weekly_review(ctx: ToolContext) -> dict:
    return planner.weekly_review(ctx)


def get_productivity_insights(ctx: ToolContext) -> dict:
    m = insights.compute_metrics(ctx.user_id)
    items = insights.rule_insights(m)
    return {"metrics": m, "results": [{"title": i["text"]} for i in items], "message": "Productivity insights:"}


register(Tool("generate_daily_plan", "Build an overlap-free schedule for a day around fixed events, by priority and deadline.", {
    "date": P("string", "YYYY-MM-DD, default today"), "work_start": P("string", "HH:MM"), "work_end": P("string", "HH:MM")},
    generate_daily_plan, "planner", "read"))
register(Tool("apply_daily_plan", "Write the saved plan for a date onto the calendar and tasks.", {"date": P("string", "YYYY-MM-DD")},
              apply_daily_plan, "planner", "write", lambda a: f"Apply the daily plan for {a.get('date') or 'today'}"))
register(Tool("reschedule_overdue", "Spread overdue tasks over the coming working days by priority.", {}, reschedule_overdue, "planner", "write",
              lambda a: "Reschedule all overdue tasks"))
register(Tool("weekly_review", "Reflect on the past week (metrics, wins, slips, lesson).", {}, weekly_review, "planner", "read"))
register(Tool("get_productivity_insights", "Metrics and rule-based insights about workload and progress.", {}, get_productivity_insights, "planner", "read"))
register(Tool("create_goal_plan", "Decompose a goal into milestones and tasks and save them.", {
    "goal": P("string", "the goal", True), "target_date": P("string", "YYYY-MM-DD"), "hours_per_week": P("number", "available effort"),
    "notes": P("string", "constraints/preferences")}, create_goal_plan, "goal", "write", lambda a: f"Create goal plan '{a.get('goal')}'"))
register(Tool("list_goals", "List active goals with progress.", {}, list_goals, "goal", "read"))
register(Tool("replan_goal", "Adaptive re-plan: push overdue tasks of a goal forward.", {"goal_id": P("integer", "id", True)},
              replan_goal, "goal", "write"))
