"""Dashboard analytics: deterministic metrics + rule-based insights, optionally narrated by the LLM."""
from __future__ import annotations

from datetime import timedelta

from core import repo
from core import timeparse as tp
from tools._util import ask_llm


def compute_metrics(user_id: int) -> dict:
    today = tp.today()
    t_iso = today.isoformat()
    tasks = repo.list_tasks(user_id)
    open_ = [t for t in tasks if t["status"] != "done"]
    week_ago = (today - timedelta(days=7)).isoformat()
    done_7d = [t for t in tasks if t["status"] == "done" and (t.get("completed_at") or "")[:10] >= week_ago]
    created_7d = [t for t in tasks if (t.get("created_at") or "")[:10] >= week_ago]
    today_tasks = [t for t in open_ if t.get("scheduled_date") == t_iso or t.get("due_date") == t_iso]
    done_days = {(t.get("completed_at") or "")[:10] for t in tasks if t["status"] == "done" and t.get("completed_at")}
    streak, d = 0, today
    while d.isoformat() in done_days:
        streak += 1
        d -= timedelta(days=1)
    events = repo.list_events(user_id, t_iso, (today + timedelta(days=7)).isoformat())
    return {
        "open": len(open_), "overdue": len([t for t in open_ if t.get("due_date") and t["due_date"] < t_iso]),
        "due_today": len([t for t in open_ if t.get("due_date") == t_iso]),
        "urgent_open": len([t for t in open_ if t["priority"] == "urgent"]),
        "blocked": len([t for t in open_ if t["status"] == "blocked"]),
        "done_7d": len(done_7d), "hours_done_7d": round(sum(float(t.get("estimated_hours") or 0) for t in done_7d), 1),
        "created_7d": len(created_7d), "streak": streak,
        "today_load_hours": round(sum(float(t.get("estimated_hours") or 1) for t in today_tasks), 1),
        "events_today": len([e for e in events if e["date"] == t_iso]), "events_week": len(events),
        "goals": [{"title": g["title"], "progress": g["progress"]} for g in repo.list_goals(user_id, "active")],
    }


def rule_insights(m: dict) -> list[dict]:
    out = []
    if m["overdue"]:
        out.append({"level": "warning", "text": f"{m['overdue']} task(s) are overdue — let the Planner agent reschedule them."})
    if m["today_load_hours"] > 8:
        out.append({"level": "warning", "text": f"Today's workload is {m['today_load_hours']}h — more than a working day. Defer something."})
    if m["urgent_open"] > 3:
        out.append({"level": "warning", "text": f"{m['urgent_open']} urgent tasks are open; urgency inflation hides real priorities."})
    if m["blocked"]:
        out.append({"level": "info", "text": f"{m['blocked']} task(s) are blocked — unblock or drop them."})
    if m["streak"] >= 3:
        out.append({"level": "success", "text": f"🔥 {m['streak']}-day completion streak. Keep it going!"})
    if m["done_7d"] and m["created_7d"] > m["done_7d"] * 2:
        out.append({"level": "info", "text": "You're adding work much faster than finishing it — try limiting new tasks this week."})
    for g in m["goals"]:
        if g["progress"] == 0:
            out.append({"level": "info", "text": f"Goal '{g['title']}' has no completed tasks yet — start with its first milestone."})
    if not out:
        out.append({"level": "success", "text": "Everything looks on track. Nice work!"})
    return out


def ai_narrative(ctx, m: dict) -> str | None:
    return ask_llm(ctx, "You are a concise productivity coach. Give 3 short, specific, actionable recommendations as markdown bullets.",
                   f"Metrics: {m}", role="writer", max_tokens=400)
