"""Rule-based stand-in for an LLM so the whole app can be demoed (and tested) with NO key at all.

It understands the same JSON protocol as the real agents: the supervisor returns a routing plan and
each worker picks one tool from keywords, then summarises the observation.  It is intentionally
limited - connect a free Groq / Gemini / OpenRouter key (or Ollama) for real reasoning.
"""
from __future__ import annotations

import json
import re

from core import timeparse as tp

ROUTES = {
    "planner": r"plan (my|the) day|today'?s plan|daily plan|schedule my day|weekly review|review my week|reschedule overdue|insights?",
    "email": r"\be-?mails?\b|\bgmail\b|\binbox\b|\bmail\b",
    "github": r"\bgithub\b|\brepo(s|sitor(y|ies))?\b|\bissues?\b|pull request|\bprs?\b|\bcommit",
    "research": r"\bsearch\b|\bnews\b|research|look up|\bgoogle\b|find out|\bimages?\b|\bweb\b|duckduckgo",
    "goal": r"\bgoals?\b|roadmap|milestones?|\bobjective\b|i want to (learn|build|finish|achieve|complete)",
    "calendar": r"\bmeeting\b|calendar|\bevents?\b|appointment|free (time|slot)|\bavailable\b|\bagenda\b|schedule a|\bcall with\b",
    "tasks": r"\btasks?\b|to-?do|remind|\badd\b|\bcreate\b|workboard|\bdone\b|\bcomplete",
}
ORDER = ["planner", "email", "github", "research", "goal", "calendar", "tasks"]


def _json(obj) -> str:
    return json.dumps(obj)


def _user_task(messages: list[dict]) -> str:
    for m in messages:
        if m["role"] == "user":
            txt = m["content"]
            mt = re.search(r"Task:\s*(.*?)(?:\n\nContext|\Z)", txt, re.S)
            return (mt.group(1) if mt else txt).strip()
    return ""


def _route(text: str) -> list[dict]:
    t = text.lower()
    if re.fullmatch(r"\s*(hi|hello|hey|thanks|thank you|good (morning|evening|afternoon))\W*", t):
        return []
    hits = {a: len(re.findall(p, t)) for a, p in ROUTES.items()}
    ranked = [a for a in ORDER if hits[a] > 0]
    if not ranked:
        return [{"agent": "tasks", "task": text}]
    # an explicit planner/goal/email/github intent wins over generic words
    steps = [ranked[0]]
    if len(ranked) > 1 and re.search(r"\bthen\b|and also|after that|\balso\b", t):
        steps.append(ranked[1])
    return [{"agent": a, "task": text} for a in steps]


def _clean_title(text: str) -> str:
    t = re.sub(r"(?i)^(please\s+)?(can you\s+)?(add|create|make|set up|schedule|remind me to|remind me|todo:?|task:?)\s+(a\s+|an\s+|the\s+)?(new\s+)?(task|todo|to-do|meeting|event|reminder)?\s*(called|named|to|for|about|:)?\s*", "", text.strip())
    t = re.sub(r"(?i)\b(tomorrow|today|tonight|next \w+|on \w+day|by \w+day|in \d+ days?)\b", "", t)
    t = re.sub(r"(?i)\b(at|from|by)?\s*\d{1,2}(:\d{2})?\s*(am|pm)\b(\s*(-|to|until)\s*\d{1,2}(:\d{2})?\s*(am|pm)?)?", "", t)
    t = re.sub(r"(?i)\b(with priority \w+|priority \w+|urgent|high priority|low priority|asap)\b", "", t)
    t = re.sub(r"(?i)\bfor \d+(\.\d+)? ?(hours?|hrs?|minutes?|mins?)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.-:")
    return (t[:1].upper() + t[1:]) if t else "Untitled"


def _priority(text: str) -> str:
    t = text.lower()
    if re.search(r"urgent|asap|critical", t):
        return "urgent"
    if re.search(r"\bhigh\b|important", t):
        return "high"
    if re.search(r"\blow\b|whenever|someday", t):
        return "low"
    return "medium"


def _pick_action(role: str, task: str):
    t = task.lower()
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", task)
    date = tp.parse_date(task)
    times = tp.parse_times(task)
    dur = tp.parse_duration_hours(task)
    if role == "tasks":
        if re.search(r"\b(list|show|what|pending|open|my)\b.*\b(tasks?|to-?dos?|workboard)\b|\bwhat do i have\b", t):
            return "list_tasks", {"status": "open"}
        m = re.match(r"^\s*(?:please\s+)?(?:mark|complete|done with)\s+(?:task\s+)?(.+?)(?:\s+as done|\s+as complete[d]?|\s+done)?\s*$", t)
        if m:
            return "complete_task", {"title": m.group(1).strip()}
        args = {"title": _clean_title(task), "priority": _priority(task)}
        if date:
            args["due_date"] = date
            args["scheduled_date"] = date
        if times:
            args["start_time"] = times[0]
            args["kind"] = "task"
        if dur:
            args["estimated_hours"] = dur
        return "create_task", args
    if role == "calendar":
        if re.search(r"free (time|slot)|\bavailable\b|when am i free", t):
            return "find_free_slots", {"date": date or tp.today().isoformat()}
        if re.search(r"what'?s on|\bshow\b|\blist\b|agenda|upcoming|my (calendar|events)", t) and not re.search(r"\bschedule a\b|\bbook\b", t):
            d = date or tp.today().isoformat()
            return "get_calendar_events", {"start_date": d, "end_date": d}
        start = times[0] if times else "10:00"
        end = times[1] if len(times) > 1 else tp.add_hours(start, dur or 1.0)
        about = re.search(r"(?:about|regarding|re:)\s+(.+?)$", task, re.I)
        title = about.group(1).strip().capitalize() if about else _clean_title(re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", task))
        return "schedule_meeting", {"title": title or "Meeting", "date": date or tp.today().isoformat(),
                                    "start_time": start, "end_time": end, "attendees": ",".join(emails)}
    if role == "email":
        if emails and re.search(r"\b(send|write|compose|draft|reply|mail)\b", t) and not re.search(r"\bread\b|\bcheck\b", t):
            subj = re.search(r"(?:about|subject:?|regarding)\s+(.+?)(?:\s+saying|\s+body|$)", task, re.I)
            body = re.search(r"(?:saying|body:?|message:?)\s+(.+)$", task, re.I)
            return "send_email", {"to": emails[0], "subject": (subj.group(1) if subj else "Hello").strip().capitalize(),
                                  "body": (body.group(1) if body else "Hi,\n\nFollowing up as discussed.\n\nBest regards").strip()}
        q = re.search(r"from:\S+|subject:\S+", t)
        words = re.sub(r"(?i)\b(read|check|show|get|my|latest|recent|emails?|mails?|gmail|inbox|any|new|unread)\b", "", t).strip()
        return "read_emails", {"query": q.group(0) if q else words[:60], "limit": 5}
    if role == "github":
        repo = re.search(r"\b([\w-]+)/([\w.-]+)\b", task)
        if re.search(r"notification", t):
            return "read_notifications", {}
        if re.search(r"pull request|\bprs?\b", t) and repo:
            return "list_pull_requests", {"owner": repo.group(1), "repo": repo.group(2)}
        if re.search(r"\bissues?\b", t) and repo:
            if re.search(r"\b(create|open|file|new)\b", t):
                return "create_issue", {"owner": repo.group(1), "repo": repo.group(2), "title": _clean_title(task)}
            return "list_issues", {"owner": repo.group(1), "repo": repo.group(2)}
        if repo and re.search(r"summar|explain|overview", t):
            return "summarize_repository", {"owner": repo.group(1), "repo": repo.group(2)}
        return "list_repositories", {"limit": 10}
    if role == "research":
        q = re.sub(r"(?i)^(please\s+)?(search( the web)?( for)?|look up|find out( about)?|research|google)\s*", "", task).strip()
        if re.search(r"\bnews\b", t):
            return "search_news", {"query": q or task, "limit": 5}
        if re.search(r"\bimages?\b|\bphotos?\b|\bpictures?\b", t):
            return "search_images", {"query": q or task, "limit": 4}
        return "search_web", {"query": q or task, "limit": 5}
    if role == "goal":
        return "create_goal_plan", {"goal": re.sub(r"(?i)\s+by\s+\w+\s+\d{1,2}(st|nd|rd|th)?\s*$", "", re.sub(r"(?i)^(i want to|my goal is to|set a goal( to)?)\s*", "", task).strip()).strip().capitalize(),
                                    "target_date": date or "", "hours_per_week": 6}
    if role == "planner":
        if re.search(r"weekly review|review my week", t):
            return "weekly_review", {}
        if re.search(r"reschedule overdue|overdue", t):
            return "reschedule_overdue", {}
        if re.search(r"insight", t):
            return "get_productivity_insights", {}
        return "generate_daily_plan", {"date": date or tp.today().isoformat()}
    return None


def _render_observation(text: str) -> str:
    try:
        obs = json.loads(text)
    except Exception:
        return text[:600]
    lines = [obs.get("message") or ("✅ Done." if obs.get("ok") else f"⚠️ {obs.get('error', 'Something went wrong.')}")]
    for key in ("tasks", "events", "emails", "results", "repositories", "issues", "pull_requests", "slots", "notifications"):
        items = obs.get(key)
        if isinstance(items, list) and items:
            for it in items[:8]:
                if isinstance(it, dict):
                    label = it.get("title") or it.get("subject") or it.get("name") or it.get("full_name") or it.get("summary") or str(it)[:80]
                    extra = it.get("when") or it.get("due_date") or it.get("sender") or it.get("href") or it.get("url") or ""
                    lines.append(f"- {label}" + (f" — {extra}" if extra else ""))
                else:
                    lines.append(f"- {it}")
    if obs.get("plan_summary"):
        lines.append(obs["plan_summary"])
    return "\n".join(lines)


def offline_chat(messages: list[dict], role: str = "") -> str:
    role = role or "tasks"
    if role == "supervisor":
        text = _user_task(messages)
        steps = _route(text)
        if not steps:
            return _json({"steps": [], "direct_answer": "Hi! I can manage your tasks, calendar, email, GitHub, research and goals. What would you like to do?"})
        return _json({"steps": steps, "direct_answer": None})
    if role == "critic":
        return _json({"verdict": "pass", "issues": [], "feedback": ""})
    if role == "synthesizer":
        last = messages[-1]["content"]
        m = re.search(r"STEP RESULTS:\s*(.*)", last, re.S)
        return (m.group(1) if m else last).strip()[:3000]
    if role in ("tasks", "calendar", "email", "github", "research", "goal", "planner"):
        last = messages[-1]["content"]
        if last.startswith("Observation:"):
            return _json({"final": _render_observation(last[len("Observation:"):].strip())})
        action = _pick_action(role, _user_task(messages))
        if not action:
            return _json({"final": "I'm not sure how to help with that in offline mode."})
        return _json({"thought": f"Offline heuristic picked {action[0]}", "action": action[0], "args": action[1]})
    return "Offline demo mode: connect a free LLM provider (Groq, Gemini, OpenRouter or Ollama) in Settings for this feature."
