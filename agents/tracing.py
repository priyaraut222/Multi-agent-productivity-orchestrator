"""Run tracing: every thought, tool call and observation is persisted so runs are explainable/auditable."""
from __future__ import annotations

import time
from typing import Callable

from core import repo


class Tracer:
    def __init__(self, user_id: int, query: str, on_event: Callable[[dict], None] | None = None, persist: bool = True):
        self.user_id = user_id
        self.on_event = on_event
        self.persist = persist
        self.run_id = repo.create_run(user_id, query) if persist else None
        self.idx = 0
        self.events: list[dict] = []
        self.started = time.time()

    def emit(self, agent: str, kind: str, content) -> None:
        self.idx += 1
        ev = {"idx": self.idx, "agent": agent, "kind": kind, "content": content}
        self.events.append(ev)
        if self.persist and self.run_id:
            repo.add_step(self.run_id, self.idx, agent, kind, content)
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:  # UI callbacks must never break the agent
                pass

    def finish(self, status: str, final: str, llm_calls: int) -> None:
        if self.persist and self.run_id:
            repo.finish_run(self.run_id, status, final, llm_calls, int((time.time() - self.started) * 1000))
