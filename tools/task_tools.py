"""Workboard tools (tasks & to-dos)."""
from __future__ import annotations

from core import repo
from core import timeparse as tp
from tools._util import fail
from tools.registry import Tool, ToolContext, register


def _view(t: dict) -> dict:
    when = " ".join(x for x in [t.get("scheduled_date") or "", (t.get("start_time") or "")] if x)
    return {"id": t["id"], "title": t["title"], "priority": t["priority"], "status": t["status"], "kind": t["kind"],
            "due_date": t.get("due_date"), "when": when or None, "estimated_hours": t.get("estimated_hours"),
            "goal_id": t.get("goal_id")}


def create_task(ctx: ToolContext, title: str, description: str = "", priority: str = "medium", due_date: str = "",
                scheduled_date: str = "", start_time: str = "", end_time: str = "", estimated_hours: float = 1.0,
                kind: str = "", category: str = "", link: str = "", goal_id: int = 0) -> dict:
    start = tp.normalize_time(start_time)
    end = tp.normalize_time(end_time)
    if start and not end:
        end = tp.add_hours(start, float(estimated_hours or 1.0))
    sched = scheduled_date or (due_date if start else "")
    tid = repo.add_task(ctx.user_id, title, description=description, priority=(priority or "medium").lower(),
                        due_date=due_date or None, scheduled_date=sched or None, start_time=start, end_time=end,
                        estimated_hours=float(estimated_hours or 1.0), kind=kind or ("task" if start else "todo"),
                        category=category, link=link, goal_id=goal_id or None, source="agent")
    return {"task_id": tid, "message": f"✅ Added {'task' if start else 'to-do'} #{tid}: {title}"
            + (f" ({sched} {start}-{end})" if start and sched else (f" (due {due_date})" if due_date else ""))}


def list_tasks(ctx: ToolContext, status: str = "open", priority: str = "", limit: int = 20) -> dict:
    rows = repo.list_tasks(ctx.user_id, open_only=(status in ("open", "")), status=None if status in ("open", "", "all") else status)
    if priority:
        rows = [r for r in rows if r["priority"] == priority.lower()]
    rows = rows[: int(limit)]
    return {"tasks": [_view(r) for r in rows], "count": len(rows), "message": f"You have {len(rows)} matching task(s)."}


def _resolve(ctx: ToolContext, task_id: int = 0, title: str = ""):
    if task_id:
        t = repo.get_task(int(task_id), ctx.user_id)
        return (t, None) if t else (None, f"Task #{task_id} not found.")
    matches = [m for m in repo.search_tasks(ctx.user_id, title) if m["status"] != "done"]
    if not matches:
        return None, f"No open task matching '{title}'."
    exact = [m for m in matches if m["title"].lower() == title.lower()]
    if len(exact) == 1 or len(matches) == 1:
        return (exact or matches)[0], None
    return None, "Several tasks match: " + "; ".join(f"#{m['id']} {m['title']}" for m in matches[:5]) + ". Use task_id."


def complete_task(ctx: ToolContext, task_id: int = 0, title: str = "") -> dict:
    t, err = _resolve(ctx, task_id, title)
    if err:
        return fail(err)
    repo.update_task(t["id"], ctx.user_id, status="done")
    return {"task_id": t["id"], "message": f"🎉 Marked '{t['title']}' as done."}


def update_task(ctx: ToolContext, task_id: int, title: str = "", status: str = "", priority: str = "", due_date: str = "",
                scheduled_date: str = "", start_time: str = "", end_time: str = "", estimated_hours: float = 0,
                description: str = "") -> dict:
    fields = {"title": title, "status": status, "priority": priority, "due_date": due_date,
              "scheduled_date": scheduled_date, "start_time": tp.normalize_time(start_time),
              "end_time": tp.normalize_time(end_time), "estimated_hours": estimated_hours or None,
              "description": description}
    fields = {k: v for k, v in fields.items() if v not in ("", None)}
    if not fields:
        return fail("Nothing to update.")
    if not repo.update_task(int(task_id), ctx.user_id, **fields):
        return fail(f"Task #{task_id} not found.")
    return {"message": f"✏️ Updated task #{task_id}.", "updated": list(fields)}


def delete_task(ctx: ToolContext, task_id: int) -> dict:
    return {"message": f"🗑️ Deleted task #{task_id}."} if repo.delete_task(int(task_id), ctx.user_id) else fail("Task not found.")


def assign_task(ctx: ToolContext, task_id: int, collaborator: str) -> dict:
    people = {c["username"].lower(): c for c in repo.list_collaborators(ctx.user_id)}
    people.update({c["email"].lower(): c for c in repo.list_collaborators(ctx.user_id)})
    person = people.get(collaborator.lower())
    if not person:
        return fail(f"'{collaborator}' is not one of your collaborators.", collaborators=sorted({p['username'] for p in people.values()}))
    if not repo.update_task(int(task_id), ctx.user_id, assignee_id=person["id"]):
        return fail("Task not found.")
    return {"message": f"👥 Assigned task #{task_id} to {person['username']}."}


P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731

register(Tool("create_task", "Create a task/to-do on the workboard (optionally time-boxed).", {
    "title": P("string", "short title", True), "description": P("string", "details"),
    "priority": P("string", "low|medium|high|urgent"), "due_date": P("string", "YYYY-MM-DD"),
    "scheduled_date": P("string", "YYYY-MM-DD when it will be worked on"), "start_time": P("string", "HH:MM"),
    "end_time": P("string", "HH:MM"), "estimated_hours": P("number", "effort in hours"),
    "kind": P("string", "todo|task"), "category": P("string", "label"), "goal_id": P("integer", "link to a goal")},
    create_task, "tasks", "write", lambda a: f"Create task '{a.get('title')}'" + (f" due {a['due_date']}" if a.get("due_date") else "")))
register(Tool("list_tasks", "List workboard tasks.", {
    "status": P("string", "open|todo|in_progress|blocked|done|all"), "priority": P("string", "filter"), "limit": P("integer", "max rows")},
    list_tasks, "tasks", "read"))
register(Tool("complete_task", "Mark a task done by id or title.", {"task_id": P("integer", "id"), "title": P("string", "title text")},
              complete_task, "tasks", "write", lambda a: f"Complete task {a.get('task_id') or a.get('title')}"))
register(Tool("update_task", "Change fields of a task.", {
    "task_id": P("integer", "id", True), "title": P("string", ""), "status": P("string", "todo|in_progress|blocked|done"),
    "priority": P("string", ""), "due_date": P("string", "YYYY-MM-DD"), "scheduled_date": P("string", "YYYY-MM-DD"),
    "start_time": P("string", "HH:MM"), "end_time": P("string", "HH:MM"), "estimated_hours": P("number", ""),
    "description": P("string", "")}, update_task, "tasks", "write", lambda a: f"Update task #{a.get('task_id')}"))
register(Tool("delete_task", "Delete a task permanently.", {"task_id": P("integer", "id", True)}, delete_task, "tasks", "write",
              lambda a: f"Delete task #{a.get('task_id')}"))
register(Tool("assign_task", "Assign a task to one of the user's collaborators.", {
    "task_id": P("integer", "id", True), "collaborator": P("string", "username or email", True)}, assign_task, "tasks", "write",
    lambda a: f"Assign task #{a.get('task_id')} to {a.get('collaborator')}"))
