"""Long-term memory tools shared by every agent."""
from __future__ import annotations

from core import repo
from tools.registry import Tool, ToolContext, register


def remember(ctx: ToolContext, content: str, kind: str = "fact", importance: int = 3) -> dict:
    kind = kind if kind in ("fact", "preference", "habit", "lesson") else "fact"
    mid = repo.add_memory(ctx.user_id, content, kind, max(1, min(int(importance), 5)))
    return {"memory_id": mid, "message": f"🧠 Remembered: {content}"}


def recall(ctx: ToolContext, query: str, limit: int = 5) -> dict:
    mems = repo.search_memories(ctx.user_id, query, int(limit))
    return {"memories": [{"kind": m["kind"], "content": m["content"]} for m in mems], "count": len(mems),
            "message": f"Found {len(mems)} relevant memories."}


register(Tool("remember", "Save a durable fact, preference, habit or lesson about the user.", {
    "content": {"type": "string", "description": "the thing to remember", "required": True},
    "kind": {"type": "string", "description": "fact|preference|habit|lesson"},
    "importance": {"type": "integer", "description": "1-5"}}, remember, "memory", "write"))
register(Tool("recall", "Search long-term memory.", {"query": {"type": "string", "description": "keywords", "required": True},
                                                    "limit": {"type": "integer", "description": "max"}}, recall, "memory", "read"))
