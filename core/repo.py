"""Data-access layer: every SQL statement of the app lives here."""
from __future__ import annotations

import json
from datetime import datetime

from core import crypto, db, security
from core import timeparse as tp

PRIORITIES = ("low", "medium", "high", "urgent")
STATUSES = ("todo", "in_progress", "blocked", "done")
TASK_FIELDS = {"created_at", "updated_at", 
    "title", "description", "kind", "status", "priority", "category", "tags", "estimated_hours",
    "actual_hours", "due_date", "scheduled_date", "start_time", "end_time", "link", "source",
    "goal_id", "milestone_id", "assignee_id",
}


def _now() -> str:
    return tp.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ users
def create_user(username: str, password: str, email: str, full_name: str = "") -> int | None:
    try:
        return db.execute(
            "INSERT INTO users (username, password_hash, email, full_name) VALUES (?,?,?,?)",
            (username.strip(), security.hash_password(password), email.strip().lower(), full_name.strip()),
        )
    except Exception:
        return None


def authenticate(username: str, password: str) -> dict | None:
    row = db.query("SELECT * FROM users WHERE username = ?", (username.strip(),), one=True)
    if row and security.verify_password(password, row["password_hash"]):
        row.pop("password_hash")
        return row
    return None


def get_user(user_id: int) -> dict | None:
    row = db.query("SELECT id, username, email, full_name FROM users WHERE id = ?", (user_id,), one=True)
    return row


def update_user(user_id: int, email: str, full_name: str) -> None:
    db.execute("UPDATE users SET email=?, full_name=? WHERE id=?", (email.strip().lower(), full_name.strip(), user_id))


def set_password(user_id: int, password: str) -> None:
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (security.hash_password(password), user_id))


# ------------------------------------------------------------------ sessions (survive OAuth redirects)
def create_session(user_id: int, days: int = 7) -> str:
    import secrets
    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    expires = (tp.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("DELETE FROM sessions WHERE user_id=? AND expires_at < ?", (user_id, _now()))
    db.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    return token


def validate_session(token: str) -> dict | None:
    if not token:
        return None
    row = db.query("SELECT u.id, u.username, u.email, u.full_name FROM sessions s JOIN users u ON u.id=s.user_id "
                   "WHERE s.token=? AND s.expires_at > ?", (token, _now()), one=True)
    return row


def delete_session(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token=?", (token,))


# ------------------------------------------------------------------ settings & tokens
def get_setting(user_id: int, key: str, default=None):
    row = db.query("SELECT value, encrypted FROM user_settings WHERE user_id=? AND key=?", (user_id, key), one=True)
    if not row or row["value"] is None:
        return default
    return (crypto.decrypt(row["value"]) if row["encrypted"] else row["value"]) or default


def set_setting(user_id: int, key: str, value, encrypted: bool = False) -> None:
    if value is None or value == "":
        db.execute("DELETE FROM user_settings WHERE user_id=? AND key=?", (user_id, key))
        return
    stored = crypto.encrypt(str(value)) if encrypted else str(value)
    db.execute(
        "INSERT INTO user_settings (user_id, key, value, encrypted) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, encrypted=excluded.encrypted",
        (user_id, key, stored, int(encrypted)),
    )


def save_token(user_id: int, provider: str, data: dict) -> None:
    db.execute(
        "INSERT INTO oauth_tokens (user_id, provider, data, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id, provider) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (user_id, provider, crypto.encrypt(json.dumps(data)), _now()),
    )


def get_token(user_id: int, provider: str) -> dict | None:
    row = db.query("SELECT data FROM oauth_tokens WHERE user_id=? AND provider=?", (user_id, provider), one=True)
    if not row:
        return None
    raw = crypto.decrypt(row["data"])
    return json.loads(raw) if raw else None


def delete_token(user_id: int, provider: str) -> None:
    db.execute("DELETE FROM oauth_tokens WHERE user_id=? AND provider=?", (user_id, provider))


# ------------------------------------------------------------------ tasks
def add_task(user_id: int, title: str, **fields) -> int:
    clean = {k: v for k, v in fields.items() if k in TASK_FIELDS and v not in (None, "")}
    if clean.get("priority") not in PRIORITIES:
        clean["priority"] = "medium"
    if clean.get("status") not in STATUSES:
        clean["status"] = "todo"
    clean.setdefault("created_at", _now())
    clean.setdefault("updated_at", clean["created_at"])
    cols = ["user_id", "title"] + list(clean)
    vals = [user_id, title.strip()] + list(clean.values())
    return db.execute(f"INSERT INTO tasks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(vals))


def get_task(task_id: int, user_id: int | None = None) -> dict | None:
    row = db.query("SELECT * FROM tasks WHERE id=?", (task_id,), one=True)
    if row and user_id is not None and user_id not in (row["user_id"], row["assignee_id"]):
        return None
    return row


def update_task(task_id: int, user_id: int, **fields) -> bool:
    clean = {k: v for k, v in fields.items() if k in TASK_FIELDS}
    if not clean or not get_task(task_id, user_id):
        return False
    if clean.get("status") == "done":
        clean["completed_at"] = _now()
    elif "status" in clean:
        clean["completed_at"] = None
    clean["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in clean)
    db.execute(f"UPDATE tasks SET {sets} WHERE id=?", tuple(clean.values()) + (task_id,))
    return True


def delete_task(task_id: int, user_id: int) -> bool:
    if not get_task(task_id, user_id):
        return False
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return True


def list_tasks(user_id: int, status: str | None = None, kind: str | None = None, open_only: bool = False,
               goal_id: int | None = None, scheduled_date: str | None = None, limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM tasks WHERE (user_id=? OR assignee_id=?)"
    params: list = [user_id, user_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if open_only:
        sql += " AND status != 'done'"
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    if goal_id:
        sql += " AND goal_id=?"
        params.append(goal_id)
    if scheduled_date:
        sql += " AND scheduled_date=?"
        params.append(scheduled_date)
    sql += (" ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,"
            " COALESCE(due_date,'9999-12-31'), id LIMIT ?")
    params.append(limit)
    return db.query(sql, tuple(params))


def search_tasks(user_id: int, text: str, limit: int = 10) -> list[dict]:
    like = f"%{text}%"
    return db.query(
        "SELECT * FROM tasks WHERE (user_id=? OR assignee_id=?) AND (title LIKE ? OR description LIKE ?) "
        "ORDER BY id DESC LIMIT ?", (user_id, user_id, like, like, limit))


# ------------------------------------------------------------------ events
def add_event(user_id: int, title: str, date: str, start_time: str | None = None, end_time: str | None = None,
              description: str = "", event_type: str = "meeting", attendees: str = "", meeting_link: str = "",
              google_event_id: str | None = None, task_id: int | None = None) -> int:
    return db.execute(
        "INSERT INTO events (user_id, task_id, title, description, event_type, date, start_time, end_time, "
        "attendees, meeting_link, google_event_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, task_id, title.strip(), description, event_type, date, start_time, end_time, attendees,
         meeting_link, google_event_id))


def get_event(event_id: int, user_id: int) -> dict | None:
    return db.query("SELECT * FROM events WHERE id=? AND user_id=?", (event_id, user_id), one=True)


def update_event(event_id: int, user_id: int, **fields) -> bool:
    allowed = {"title", "description", "event_type", "date", "start_time", "end_time", "attendees",
               "meeting_link", "google_event_id"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean or not get_event(event_id, user_id):
        return False
    db.execute(f"UPDATE events SET {', '.join(k + '=?' for k in clean)} WHERE id=?",
               tuple(clean.values()) + (event_id,))
    return True


def delete_event(event_id: int, user_id: int) -> bool:
    if not get_event(event_id, user_id):
        return False
    db.execute("DELETE FROM events WHERE id=?", (event_id,))
    return True


def list_events(user_id: int, start_date: str, end_date: str | None = None) -> list[dict]:
    end_date = end_date or start_date
    return db.query(
        "SELECT * FROM events WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date, COALESCE(start_time,'')",
        (user_id, start_date, end_date))


def find_conflicts(user_id: int, date: str, start: str, end: str, exclude_id: int | None = None) -> list[dict]:
    out = []
    s, e = tp.to_minutes(start), tp.to_minutes(end)
    for ev in list_events(user_id, date):
        if exclude_id and ev["id"] == exclude_id:
            continue
        if ev["start_time"] and ev["end_time"]:
            if s < tp.to_minutes(ev["end_time"]) and tp.to_minutes(ev["start_time"]) < e:
                out.append(ev)
    return out


# ------------------------------------------------------------------ goals
def add_goal(user_id: int, title: str, description: str = "", target_date: str | None = None) -> int:
    return db.execute("INSERT INTO goals (user_id, title, description, target_date) VALUES (?,?,?,?)",
                      (user_id, title.strip(), description, target_date))


def list_goals(user_id: int, status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM goals WHERE user_id=?", [user_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    goals = db.query(sql + " ORDER BY id DESC", tuple(params))
    for g in goals:
        g.update(goal_progress(g["id"]))
    return goals


def get_goal(goal_id: int, user_id: int) -> dict | None:
    g = db.query("SELECT * FROM goals WHERE id=? AND user_id=?", (goal_id, user_id), one=True)
    if g:
        g.update(goal_progress(goal_id))
    return g


def goal_progress(goal_id: int) -> dict:
    rows = db.query("SELECT status, COUNT(*) AS n FROM tasks WHERE goal_id=? GROUP BY status", (goal_id,))
    total = sum(r["n"] for r in rows)
    done = sum(r["n"] for r in rows if r["status"] == "done")
    return {"total_tasks": total, "done_tasks": done, "progress": round(done / total, 3) if total else 0.0}


def add_milestone(goal_id: int, title: str, due_date: str | None = None) -> int:
    return db.execute("INSERT INTO milestones (goal_id, title, due_date) VALUES (?,?,?)", (goal_id, title, due_date))


def list_milestones(goal_id: int) -> list[dict]:
    return db.query("SELECT * FROM milestones WHERE goal_id=? ORDER BY COALESCE(due_date,'9999'), id", (goal_id,))


def update_goal(goal_id: int, user_id: int, **fields) -> bool:
    allowed = {"title", "description", "target_date", "status"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean or not get_goal(goal_id, user_id):
        return False
    db.execute(f"UPDATE goals SET {', '.join(k + '=?' for k in clean)} WHERE id=?",
               tuple(clean.values()) + (goal_id,))
    return True


# ------------------------------------------------------------------ memory
def add_memory(user_id: int, content: str, kind: str = "fact", importance: int = 3) -> int:
    existing = db.query("SELECT id FROM memories WHERE user_id=? AND lower(content)=lower(?)",
                        (user_id, content.strip()), one=True)
    if existing:
        return existing["id"]
    return db.execute("INSERT INTO memories (user_id, kind, content, importance) VALUES (?,?,?,?)",
                      (user_id, kind, content.strip(), importance))


def list_memories(user_id: int, limit: int = 200) -> list[dict]:
    return db.query("SELECT * FROM memories WHERE user_id=? ORDER BY importance DESC, id DESC LIMIT ?",
                    (user_id, limit))


def delete_memory(memory_id: int, user_id: int) -> None:
    db.execute("DELETE FROM memories WHERE id=? AND user_id=?", (memory_id, user_id))


_STOP = {"the", "a", "an", "to", "and", "or", "of", "for", "in", "on", "my", "me", "i", "is", "it", "with", "at",
         "please", "can", "you", "that", "this", "be", "do", "have", "what", "how", "about"}


def search_memories(user_id: int, text: str, limit: int = 5) -> list[dict]:
    """Keyword-overlap retrieval (no embeddings needed => free & offline)."""
    words = {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w not in _STOP and len(w) > 2}
    scored = []
    for m in list_memories(user_id):
        mw = {w for w in "".join(c.lower() if c.isalnum() else " " for c in m["content"]).split()}
        overlap = len(words & mw)
        if overlap or m["kind"] == "preference":
            scored.append((overlap * 2 + m["importance"], m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:limit]]


# ------------------------------------------------------------------ approvals & runs
def create_approval(user_id: int, tool: str, args: dict, summary: str, agent: str = "", run_id: int | None = None) -> int:
    return db.execute("INSERT INTO approvals (user_id, run_id, agent, tool, args, summary) VALUES (?,?,?,?,?,?)",
                      (user_id, run_id, agent, tool, json.dumps(args, default=str), summary))


def get_approval(approval_id: int, user_id: int) -> dict | None:
    row = db.query("SELECT * FROM approvals WHERE id=? AND user_id=?", (approval_id, user_id), one=True)
    if row:
        row["args"] = json.loads(row["args"])
    return row


def list_approvals(user_id: int, status: str | None = "pending", run_id: int | None = None, limit: int = 100) -> list[dict]:
    sql, params = "SELECT * FROM approvals WHERE user_id=?", [user_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if run_id:
        sql += " AND run_id=?"
        params.append(run_id)
    rows = db.query(sql + " ORDER BY id DESC LIMIT ?", tuple(params + [limit]))
    for r in rows:
        r["args"] = json.loads(r["args"])
    return rows


def resolve_approval(approval_id: int, status: str, result: dict | None = None) -> None:
    db.execute("UPDATE approvals SET status=?, result=?, resolved_at=? WHERE id=?",
               (status, json.dumps(result, default=str) if result is not None else None, _now(), approval_id))


def create_run(user_id: int, query: str) -> int:
    return db.execute("INSERT INTO agent_runs (user_id, query) VALUES (?,?)", (user_id, query))


def finish_run(run_id: int, status: str, final: str, llm_calls: int, duration_ms: int) -> None:
    db.execute("UPDATE agent_runs SET status=?, final=?, llm_calls=?, duration_ms=?, finished_at=? WHERE id=?",
               (status, final, llm_calls, duration_ms, _now(), run_id))


def add_step(run_id: int, idx: int, agent: str, kind: str, content) -> None:
    db.execute("INSERT INTO agent_steps (run_id, idx, agent, kind, content) VALUES (?,?,?,?,?)",
               (run_id, idx, agent, kind, json.dumps(content, default=str)))


def list_runs(user_id: int, limit: int = 30) -> list[dict]:
    return db.query("SELECT * FROM agent_runs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


def list_steps(run_id: int) -> list[dict]:
    rows = db.query("SELECT * FROM agent_steps WHERE run_id=? ORDER BY idx, id", (run_id,))
    for r in rows:
        try:
            r["content"] = json.loads(r["content"])
        except Exception:
            pass
    return rows


def add_chat(user_id: int, role: str, content: str, run_id: int | None = None) -> None:
    db.execute("INSERT INTO chat_messages (user_id, role, content, run_id) VALUES (?,?,?,?)",
               (user_id, role, content, run_id))


def list_chat(user_id: int, limit: int = 40) -> list[dict]:
    rows = db.query("SELECT * FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))


def clear_chat(user_id: int) -> None:
    db.execute("DELETE FROM chat_messages WHERE user_id=?", (user_id,))


# ------------------------------------------------------------------ plans
def save_plan(user_id: int, date: str, plan: dict) -> None:
    db.execute("INSERT INTO daily_plans (user_id, date, plan) VALUES (?,?,?) "
               "ON CONFLICT(user_id, date) DO UPDATE SET plan=excluded.plan, created_at=CURRENT_TIMESTAMP",
               (user_id, date, json.dumps(plan, default=str)))


def get_plan(user_id: int, date: str) -> dict | None:
    row = db.query("SELECT plan FROM daily_plans WHERE user_id=? AND date=?", (user_id, date), one=True)
    return json.loads(row["plan"]) if row else None


# ------------------------------------------------------------------ collaborators
def search_users(user_id: int, term: str, limit: int = 10) -> list[dict]:
    like = f"%{term}%"
    return db.query("SELECT id, username, email, full_name FROM users WHERE id != ? AND "
                    "(username LIKE ? OR email LIKE ?) LIMIT ?", (user_id, like, like, limit))


def send_collab_request(sender_id: int, receiver_id: int) -> bool:
    if sender_id == receiver_id:
        return False
    reverse = db.query("SELECT id FROM collaborations WHERE sender_id=? AND receiver_id=? AND status='pending'",
                       (receiver_id, sender_id), one=True)
    if reverse:  # they already asked us -> accept instead of duplicating
        db.execute("UPDATE collaborations SET status='accepted' WHERE id=?", (reverse["id"],))
        return True
    try:
        db.execute("INSERT INTO collaborations (sender_id, receiver_id) VALUES (?,?)", (sender_id, receiver_id))
        return True
    except Exception:
        return False


def incoming_requests(user_id: int) -> list[dict]:
    return db.query("SELECT c.id AS request_id, u.id AS sender_id, u.username, u.email FROM collaborations c "
                    "JOIN users u ON u.id=c.sender_id WHERE c.receiver_id=? AND c.status='pending'", (user_id,))


def respond_request(request_id: int, user_id: int, accept: bool) -> None:
    db.execute("UPDATE collaborations SET status=? WHERE id=? AND receiver_id=?",
               ("accepted" if accept else "rejected", request_id, user_id))


def list_collaborators(user_id: int) -> list[dict]:
    return db.query(
        "SELECT u.id, u.username, u.email, u.full_name FROM users u WHERE u.id IN ("
        " SELECT receiver_id FROM collaborations WHERE sender_id=? AND status='accepted' UNION "
        " SELECT sender_id FROM collaborations WHERE receiver_id=? AND status='accepted')", (user_id, user_id))


def remove_collaborator(user_id: int, other_id: int) -> None:
    db.execute("DELETE FROM collaborations WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)",
               (user_id, other_id, other_id, user_id))
