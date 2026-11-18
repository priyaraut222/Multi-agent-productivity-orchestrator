"""Planning engine: daily plan (constraint scheduler + LLM advice + validation), overdue recovery, weekly review."""
from __future__ import annotations

from datetime import timedelta
from datetime import date as _date

from core import config, repo, scheduler
from core import timeparse as tp
from tools._util import ask_llm_json


def candidate_tasks(user_id: int, date: str, blocked_ids: set[int]) -> list[dict]:
    out = []
    for t in repo.list_tasks(user_id, open_only=True):
        if t["id"] in blocked_ids:
            continue
        due, sched = t.get("due_date"), t.get("scheduled_date")
        if sched == date or (due and due <= date) or (not sched and t["priority"] in ("high", "urgent")) \
                or (not sched and not due and t["kind"] == "task"):
            out.append(t)
    return out


def _round_up(hhmm: str, step: int = 15) -> str:
    m = tp.to_minutes(hhmm)
    return tp.from_minutes(((m + step - 1) // step) * step)


def generate_plan(ctx, date: str | None = None, work_start: str | None = None, work_end: str | None = None) -> dict:
    uid = ctx.user_id
    date = date or tp.today().isoformat()
    ws = work_start or repo.get_setting(uid, "work_start", config.WORK_START)
    we = work_end or repo.get_setting(uid, "work_end", config.WORK_END)
    events = repo.list_events(uid, date)
    fixed = [e for e in events if e["start_time"] and e["end_time"]]
    blocked = {e["task_id"] for e in events if e["event_type"] == "task" and e.get("task_id")}
    # earlier 'focus' blocks from a previous plan are replaced, not treated as fixed commitments
    fixed = [e for e in fixed if e["event_type"] != "focus"]
    tasks = candidate_tasks(uid, date, blocked)
    earliest = None
    if date == tp.today().isoformat():
        earliest = _round_up(tp.now().strftime("%H:%M"))
        if tp.to_minutes(earliest) >= tp.to_minutes(we):
            earliest = None
    result = scheduler.build_schedule(tasks, fixed, date, ws, we, earliest_start=earliest)
    problems = scheduler.validate_schedule(result.slots)

    focus_ids = [s.task_id for s in result.slots if not s.fixed and s.task_id][:3]
    focus_titles = list(dict.fromkeys(next((t["title"] for t in tasks if t["id"] == i), "") for i in focus_ids))
    narrative = (f"{len([s for s in result.slots if not s.fixed])} focus block(s) planned around "
                 f"{len([s for s in result.slots if s.fixed])} fixed commitment(s). Top priorities: "
                 + (", ".join(focus_titles) or "none") + ".")
    tips: list[str] = []
    memories = [m["content"] for m in repo.list_memories(uid, 8)]
    advice = ask_llm_json(
        ctx, 'You are a productivity coach. Return JSON {"narrative": "<=60 words explaining the plan", "tips": ["max 3 short tips"]}. '
             "Respect the user's memories. Do NOT change times.",
        f"Date {date}. Plan: " + "; ".join(f"{s.start}-{s.end} {s.title} ({s.reason})" for s in result.slots)
        + f". Unscheduled: {[u['title'] for u in result.unscheduled]}. Memories: {memories}", role="writer", max_tokens=500)
    if isinstance(advice, dict):
        narrative = str(advice.get("narrative") or narrative)
        tips = [str(x) for x in (advice.get("tips") or [])][:3]
    plan = {"date": date, "slots": [s.__dict__ for s in result.slots], "unscheduled": result.unscheduled,
            "focus": focus_titles, "narrative": narrative, "tips": tips, "warnings": problems,
            "work_hours": f"{ws}-{we}"}
    repo.save_plan(uid, date, plan)
    return plan


def plan_summary(plan: dict) -> str:
    lines = [plan["narrative"]]
    for s in plan["slots"]:
        lines.append(f"- {s['start']}–{s['end']}  {s['title']}" + ("  🔒" if s["fixed"] else f"  ({s['reason']})"))
    for u in plan["unscheduled"]:
        lines.append(f"- ⚠️ Not scheduled: {u['title']} — {u['reason']}")
    for t in plan.get("tips", []):
        lines.append(f"💡 {t}")
    return "\n".join(lines)


def apply_plan(user_id: int, plan: dict) -> int:
    """Write the plan to the workboard and calendar (idempotent: replaces earlier focus blocks of that day)."""
    date = plan["date"]
    for e in repo.list_events(user_id, date):
        if e["event_type"] == "focus":
            repo.delete_event(e["id"], user_id)
    seen: set[int] = set()
    n = 0
    for s in plan["slots"]:
        if s["fixed"]:
            continue
        if s["task_id"] and s["task_id"] not in seen:
            seen.add(s["task_id"])
            repo.update_task(s["task_id"], user_id, scheduled_date=date, start_time=s["start"], end_time=s["end"], kind="task")
        repo.add_event(user_id, s["title"], date, s["start"], s["end"], s.get("reason", ""), "focus", task_id=s["task_id"])
        n += 1
    return n


def reschedule_overdue(user_id: int) -> list[dict]:
    """Recover from slipped work: spread overdue tasks across the next working days by priority."""
    today = tp.today()
    overdue = [t for t in repo.list_tasks(user_id, open_only=True) if t.get("due_date") and t["due_date"] < today.isoformat()]
    moves, day, load = [], today, 0.0
    for t in sorted(overdue, key=lambda x: -scheduler.score(x, today.isoformat())):
        hrs = float(t.get("estimated_hours") or 1)
        if load + hrs > 6:
            day, load = day + timedelta(days=1), 0.0
        while day.weekday() >= 5:
            day += timedelta(days=1)
        new = day.isoformat()
        repo.update_task(t["id"], user_id, due_date=new, scheduled_date=new, start_time=None, end_time=None)
        moves.append({"id": t["id"], "title": t["title"], "old_due": t["due_date"], "new_due": new})
        load += hrs
    return moves


def weekly_review(ctx) -> dict:
    from agents import insights

    uid = ctx.user_id
    m = insights.compute_metrics(uid)
    text = f"This week you completed {m['done_7d']} task(s) ({m['hours_done_7d']}h). {m['overdue']} overdue, {m['open']} open."
    advice = ask_llm_json(
        ctx, 'You are a reflective productivity coach. Return JSON {"wins": [..], "slips": [..], "lesson": "one sentence", "next_week": [..]} based on the metrics.',
        str(m), role="writer", max_tokens=600)
    review = {"metrics": m, "summary": text}
    if isinstance(advice, dict):
        review.update({k: advice.get(k) for k in ("wins", "slips", "lesson", "next_week")})
        if advice.get("lesson"):
            repo.add_memory(uid, str(advice["lesson"]), "lesson", 3)   # the system learns from its own reviews
        text += "\n" + "\n".join(f"- {k}: {v}" for k, v in advice.items() if v)
    review["message"] = text
    return review
