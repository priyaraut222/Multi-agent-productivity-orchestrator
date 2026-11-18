"""Calendar tools. The local calendar is always available; Google Calendar is synced when connected."""
from __future__ import annotations

import re
import uuid

from core import repo
from core import timeparse as tp
from integrations import google
from tools._util import fail
from tools.registry import Tool, ToolContext, register

P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731


def _ev_view(e: dict) -> dict:
    span = f"{e['start_time']}-{e['end_time']}" if e.get("start_time") and e.get("end_time") else (e.get("start_time") or "all day")
    return {"id": e["id"], "title": e["title"], "when": f"{e['date']} {span}", "type": e["event_type"],
            "attendees": e.get("attendees") or "", "meeting_link": e.get("meeting_link") or ""}


def sync_google(user_id: int, start: str, end: str) -> int:
    """Import Google events into the local calendar (deduplicated by google_event_id). Returns imported count."""
    if not google.is_connected(user_id, "google_calendar"):
        return 0
    known = {e["google_event_id"] for e in repo.list_events(user_id, start, end) if e.get("google_event_id")}
    n = 0
    for g in google.calendar_list_events(user_id, start, end):
        if g["google_event_id"] not in known:
            repo.add_event(user_id, g["title"], g["date"], g["start_time"], g["end_time"], g["description"], "meeting",
                           g["attendees"], g["meeting_link"], g["google_event_id"])
            n += 1
    return n


def _jitsi_link(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "", title)[:20] or "Meeting"
    return f"https://meet.jit.si/{slug}-{uuid.uuid4().hex[:8]}"


def _emails(user_id: int, attendees: str) -> list[str]:
    """Accept raw emails or collaborator usernames."""
    by = {c["username"].lower(): c["email"] for c in repo.list_collaborators(user_id)}
    out = []
    for a in re.split(r"[,\s;]+", attendees or ""):
        if a:
            out.append(a if "@" in a else by.get(a.lower(), ""))
    return [e for e in out if e]


def get_calendar_events(ctx: ToolContext, start_date: str = "", end_date: str = "") -> dict:
    start = start_date or tp.today().isoformat()
    end = end_date or start
    note = ""
    try:
        sync_google(ctx.user_id, start, end)
    except Exception as exc:
        note = f" (Google sync skipped: {exc})"
    events = repo.list_events(ctx.user_id, start, end)
    return {"events": [_ev_view(e) for e in events], "count": len(events),
            "message": f"{len(events)} event(s) between {start} and {end}.{note}"}


def check_schedule_conflicts(ctx: ToolContext, date: str, start_time: str, end_time: str) -> dict:
    s, e = tp.normalize_time(start_time), tp.normalize_time(end_time)
    if not (s and e):
        return fail("start_time and end_time must be valid times.")
    c = repo.find_conflicts(ctx.user_id, date, s, e)
    return {"conflicts": [_ev_view(x) for x in c], "has_conflict": bool(c),
            "message": "No conflicts." if not c else f"Conflicts with: {', '.join(x['title'] for x in c)}"}


def find_free_slots(ctx: ToolContext, date: str = "", duration_hours: float = 1.0, work_start: str = "09:00", work_end: str = "18:00") -> dict:
    from core.scheduler import _free_windows

    date = date or tp.today().isoformat()
    busy = [(tp.to_minutes(e["start_time"]), tp.to_minutes(e["end_time"])) for e in repo.list_events(ctx.user_id, date)
            if e["start_time"] and e["end_time"]]
    need = int(float(duration_hours) * 60)
    slots = [{"title": f"{tp.from_minutes(a)}-{tp.from_minutes(b)}", "start": tp.from_minutes(a), "end": tp.from_minutes(b)}
             for a, b in _free_windows(tp.to_minutes(work_start), tp.to_minutes(work_end), busy) if b - a >= need]
    return {"date": date, "slots": slots, "message": f"{len(slots)} free window(s) of ≥{duration_hours}h on {date}."}


def schedule_meeting(ctx: ToolContext, title: str, date: str, start_time: str, end_time: str = "", duration_hours: float = 1.0,
                     attendees: str = "", description: str = "", with_meet: bool = True, allow_conflict: bool = False) -> dict:
    start = tp.normalize_time(start_time)
    if not start or not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
        return fail("Need a valid date (YYYY-MM-DD) and start_time (HH:MM).")
    end = tp.normalize_time(end_time) or tp.add_hours(start, float(duration_hours or 1.0))
    if tp.to_minutes(end) <= tp.to_minutes(start):
        return fail("end_time must be after start_time.")
    conflicts = repo.find_conflicts(ctx.user_id, date, start, end)
    if conflicts and not allow_conflict:
        free = find_free_slots(ctx, date, (tp.to_minutes(end) - tp.to_minutes(start)) / 60)["slots"][:4]
        return fail(f"Time conflict with: {', '.join(c['title'] for c in conflicts)}.",
                    conflicts=[_ev_view(c) for c in conflicts], free_slots=free,
                    hint="Pick one of free_slots or set allow_conflict=true.")
    emails = _emails(ctx.user_id, attendees)
    link, gid, note = "", None, ""
    if with_meet and google.is_connected(ctx.user_id, "google_calendar"):
        try:
            g = google.calendar_create_event(ctx.user_id, title, date, start, end, description, emails, True)
            gid, link = g["google_event_id"], g["meeting_link"]
            note = " Synced to Google Calendar."
        except Exception as exc:
            note = f" (Google sync failed: {exc})"
    if with_meet and not link:
        link = _jitsi_link(title)
    eid = repo.add_event(ctx.user_id, title, date, start, end, description, "meeting", ",".join(emails), link, gid)
    return {"event_id": eid, "meeting_link": link, "message": f"📅 Scheduled '{title}' on {date} {start}-{end}."
            + (f" Link: {link}" if link else "") + note}


def add_task_to_calendar(ctx: ToolContext, task_id: int, date: str = "", start_time: str = "", end_time: str = "") -> dict:
    t = repo.get_task(int(task_id), ctx.user_id)
    if not t:
        return fail(f"Task #{task_id} not found.")
    date = date or t.get("scheduled_date") or t.get("due_date") or tp.today().isoformat()
    start = tp.normalize_time(start_time) or t.get("start_time") or "09:00"
    end = tp.normalize_time(end_time) or t.get("end_time") or tp.add_hours(start, float(t.get("estimated_hours") or 1))
    conflicts = repo.find_conflicts(ctx.user_id, date, start, end)
    if conflicts:
        return fail(f"Conflict with {', '.join(c['title'] for c in conflicts)}.", free_slots=find_free_slots(ctx, date)["slots"][:4])
    eid = repo.add_event(ctx.user_id, t["title"], date, start, end, t.get("description", ""), "task", task_id=t["id"])
    repo.update_task(t["id"], ctx.user_id, scheduled_date=date, start_time=start, end_time=end, kind="task")
    return {"event_id": eid, "message": f"⏱️ Blocked time for '{t['title']}' on {date} {start}-{end}."}


def reschedule_event(ctx: ToolContext, event_id: int, date: str = "", start_time: str = "", end_time: str = "") -> dict:
    ev = repo.get_event(int(event_id), ctx.user_id)
    if not ev:
        return fail("Event not found.")
    d, s = date or ev["date"], tp.normalize_time(start_time) or ev["start_time"]
    e = tp.normalize_time(end_time) or (tp.add_hours(s, (tp.to_minutes(ev["end_time"]) - tp.to_minutes(ev["start_time"])) / 60) if s and ev["end_time"] and ev["start_time"] else ev["end_time"])
    if s and e and repo.find_conflicts(ctx.user_id, d, s, e, exclude_id=ev["id"]):
        return fail("The new time conflicts with another event.")
    repo.update_event(ev["id"], ctx.user_id, date=d, start_time=s, end_time=e)
    return {"message": f"🔁 Moved '{ev['title']}' to {d} {s}-{e}."}


def delete_event(ctx: ToolContext, event_id: int) -> dict:
    ev = repo.get_event(int(event_id), ctx.user_id)
    if not ev:
        return fail("Event not found.")
    if ev.get("google_event_id") and google.is_connected(ctx.user_id, "google_calendar"):
        try:
            google.calendar_delete_event(ctx.user_id, ev["google_event_id"])
        except Exception:
            pass
    repo.delete_event(ev["id"], ctx.user_id)
    return {"message": f"🗑️ Deleted event '{ev['title']}'."}


def generate_meeting_link(ctx: ToolContext, event_id: int) -> dict:
    ev = repo.get_event(int(event_id), ctx.user_id)
    if not ev:
        return fail("Event not found.")
    link = ev.get("meeting_link") or _jitsi_link(ev["title"])
    repo.update_event(ev["id"], ctx.user_id, meeting_link=link)
    return {"meeting_link": link, "message": f"🔗 Meeting link: {link}"}


def get_collaborators(ctx: ToolContext, search: str = "") -> dict:
    people = repo.list_collaborators(ctx.user_id)
    if search:
        people = [p for p in people if search.lower() in (p["username"] + p["email"] + (p["full_name"] or "")).lower()]
    return {"collaborators": [{"title": p["username"], "email": p["email"]} for p in people], "count": len(people),
            "message": f"{len(people)} collaborator(s)."}


def add_collaborators_to_event(ctx: ToolContext, event_id: int, collaborators: str) -> dict:
    ev = repo.get_event(int(event_id), ctx.user_id)
    if not ev:
        return fail("Event not found.")
    by = {c["username"].lower(): c["email"] for c in repo.list_collaborators(ctx.user_id)}
    emails = [by.get(x.lower(), x) for x in re.split(r"[,\s;]+", collaborators) if x]
    merged = sorted(set(filter(None, (ev["attendees"] or "").split(","))) | set(emails))
    repo.update_event(ev["id"], ctx.user_id, attendees=",".join(merged))
    return {"message": f"👥 Event now has attendees: {', '.join(merged)}"}


register(Tool("get_calendar_events", "List calendar events in a date range (syncs Google Calendar if connected).", {
    "start_date": P("string", "YYYY-MM-DD"), "end_date": P("string", "YYYY-MM-DD")}, get_calendar_events, "calendar", "read"))
register(Tool("check_schedule_conflicts", "Check whether a time range collides with existing events.", {
    "date": P("string", "YYYY-MM-DD", True), "start_time": P("string", "HH:MM", True), "end_time": P("string", "HH:MM", True)},
    check_schedule_conflicts, "calendar", "read"))
register(Tool("find_free_slots", "Find free windows on a day.", {"date": P("string", "YYYY-MM-DD"), "duration_hours": P("number", "min length"),
                                                                  "work_start": P("string", "HH:MM"), "work_end": P("string", "HH:MM")},
              find_free_slots, "calendar", "read"))
register(Tool("schedule_meeting", "Create a meeting with an automatic video link (Google Meet if connected, else Jitsi). Refuses on conflicts and suggests free slots.", {
    "title": P("string", "meeting title", True), "date": P("string", "YYYY-MM-DD", True), "start_time": P("string", "HH:MM", True),
    "end_time": P("string", "HH:MM"), "duration_hours": P("number", "used if no end_time"),
    "attendees": P("string", "comma-separated emails or collaborator usernames"), "description": P("string", ""),
    "with_meet": P("boolean", "add video link"), "allow_conflict": P("boolean", "book even if overlapping")},
    schedule_meeting, "calendar", lambda a: "external" if a.get("attendees") else "write",
    lambda a: f"Schedule '{a.get('title')}' on {a.get('date')} {a.get('start_time')}" + (f" and invite {a['attendees']}" if a.get("attendees") else "")))
register(Tool("add_task_to_calendar", "Time-block an existing task on the calendar.", {
    "task_id": P("integer", "task id", True), "date": P("string", "YYYY-MM-DD"), "start_time": P("string", "HH:MM"), "end_time": P("string", "HH:MM")},
    add_task_to_calendar, "calendar", "write"))
register(Tool("reschedule_event", "Move an event.", {"event_id": P("integer", "id", True), "date": P("string", "YYYY-MM-DD"),
                                                       "start_time": P("string", "HH:MM"), "end_time": P("string", "HH:MM")},
              reschedule_event, "calendar", "write"))
register(Tool("delete_event", "Delete an event.", {"event_id": P("integer", "id", True)}, delete_event, "calendar", "write",
              lambda a: f"Delete event #{a.get('event_id')}"))
register(Tool("generate_meeting_link", "Attach a video-meeting link to an event.", {"event_id": P("integer", "id", True)},
              generate_meeting_link, "calendar", "write"))
register(Tool("get_collaborators", "Search the user's collaborators.", {"search": P("string", "name/email fragment")},
              get_collaborators, "calendar", "read"))
register(Tool("add_collaborators_to_event", "Add collaborators as attendees of an event.", {
    "event_id": P("integer", "id", True), "collaborators": P("string", "usernames/emails, comma-separated", True)},
    add_collaborators_to_event, "calendar", "write"))
