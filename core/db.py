"""SQLite persistence layer (zero-setup, free). Replaces the PostgreSQL dependency."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from core import config

_db_path = config.DB_PATH
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT DEFAULT '',
    email TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL, description TEXT DEFAULT '',
    target_date TEXT, status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    title TEXT NOT NULL, due_date TEXT, status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    milestone_id INTEGER REFERENCES milestones(id) ON DELETE SET NULL,
    title TEXT NOT NULL, description TEXT DEFAULT '',
    kind TEXT DEFAULT 'todo',            -- todo | task
    status TEXT DEFAULT 'todo',          -- todo | in_progress | blocked | done
    priority TEXT DEFAULT 'medium',      -- low | medium | high | urgent
    category TEXT DEFAULT '', tags TEXT DEFAULT '',
    estimated_hours REAL DEFAULT 1.0, actual_hours REAL DEFAULT 0,
    due_date TEXT, scheduled_date TEXT, start_time TEXT, end_time TEXT,
    link TEXT DEFAULT '', source TEXT DEFAULT 'manual',   -- manual | agent | github | gmail | goal
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    title TEXT NOT NULL, description TEXT DEFAULT '',
    event_type TEXT DEFAULT 'meeting',   -- meeting | task | focus
    date TEXT NOT NULL, start_time TEXT, end_time TEXT,
    attendees TEXT DEFAULT '', meeting_link TEXT DEFAULT '',
    google_event_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, date);
CREATE TABLE IF NOT EXISTS collaborations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending',       -- pending | accepted | rejected
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sender_id, receiver_id)
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, data TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, provider)
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL, value TEXT, encrypted INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT DEFAULT 'fact',            -- fact | preference | habit | lesson
    content TEXT NOT NULL, importance INTEGER DEFAULT 3,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id INTEGER, agent TEXT, tool TEXT NOT NULL,
    args TEXT NOT NULL, summary TEXT,
    status TEXT DEFAULT 'pending',       -- pending | executed | rejected | failed
    result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT, status TEXT DEFAULT 'running', final TEXT,
    llm_calls INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    idx INTEGER, agent TEXT, kind TEXT, content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS daily_plans (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date TEXT NOT NULL, plan TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, run_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def configure(path: str) -> None:
    """Point the app at a different database file (used by tests)."""
    global _db_path
    _db_path = path


def get_path() -> str:
    return _db_path


@contextmanager
def connection():
    if _db_path != ":memory:":
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _lock, connection() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode = WAL")


def query(sql: str, params: tuple = (), one: bool = False):
    with connection() as conn:
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write statement and return the last inserted row id."""
    with connection() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def reset_for_tests(path: str) -> None:
    configure(path)
    if path != ":memory:" and os.path.exists(path):
        os.remove(path)
    init_db()
