"""Deterministic constraint-based day scheduler.

The LLM is good at *prioritising* and *explaining*, but unreliable at arithmetic
(overlaps, durations).  So the planner agent uses this algorithm for placement and
uses the LLM only for ranking hints and the narrative.  The result is always
overlap-free and can be verified by `validate_schedule`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core import timeparse as tp

PRIORITY_WEIGHT = {"urgent": 100, "high": 60, "medium": 30, "low": 10}


@dataclass
class Slot:
    task_id: int | None
    title: str
    start: str
    end: str
    reason: str = ""
    fixed: bool = False


@dataclass
class ScheduleResult:
    slots: list[Slot] = field(default_factory=list)
    unscheduled: list[dict] = field(default_factory=list)


def score(task: dict, today_iso: str) -> float:
    s = PRIORITY_WEIGHT.get((task.get("priority") or "medium").lower(), 30)
    due = task.get("due_date")
    if due:
        days = (_d(due) - _d(today_iso)).days
        if days < 0:
            s += 80
        elif days == 0:
            s += 50
        elif days <= 2:
            s += 25
        elif days <= 7:
            s += 8
    if (task.get("status") or "") == "in_progress":
        s += 5
    # slightly favour shorter tasks so the day has quick wins
    s -= min(float(task.get("estimated_hours") or 1.0), 8) * 0.5
    return s


def _d(iso: str):
    from datetime import date

    return date.fromisoformat(str(iso)[:10])


def _free_windows(day_start: int, day_end: int, busy: list[tuple[int, int]]):
    cur, out = day_start, []
    for s, e in sorted(busy):
        if e <= cur:
            continue
        if s > cur:
            out.append((cur, min(s, day_end)))
        cur = max(cur, e)
        if cur >= day_end:
            break
    if cur < day_end:
        out.append((cur, day_end))
    return [(a, b) for a, b in out if b > a]


def build_schedule(
    tasks: list[dict],
    fixed_events: list[dict],
    today_iso: str,
    work_start: str = "09:00",
    work_end: str = "18:00",
    lunch: tuple[str, str] | None = ("13:00", "14:00"),
    buffer_min: int = 10,
    max_block_hours: float = 2.0,
    earliest_start: str | None = None,
) -> ScheduleResult:
    """Place flexible tasks around fixed events inside working hours."""
    res = ScheduleResult()
    ws, we = tp.to_minutes(work_start), tp.to_minutes(work_end)
    if earliest_start:
        ws = max(ws, tp.to_minutes(earliest_start))
    busy: list[tuple[int, int]] = []
    for ev in fixed_events:
        if ev.get("start_time") and ev.get("end_time"):
            s, e = tp.to_minutes(ev["start_time"]), tp.to_minutes(ev["end_time"])
            busy.append((s, e))
            res.slots.append(Slot(ev.get("task_id"), ev["title"], ev["start_time"][:5], ev["end_time"][:5],
                                  "Fixed commitment", fixed=True))
    if lunch:
        busy.append((tp.to_minutes(lunch[0]), tp.to_minutes(lunch[1])))

    ranked = sorted(tasks, key=lambda t: -score(t, today_iso))
    for t in ranked:
        remaining = max(float(t.get("estimated_hours") or 1.0), 0.25) * 60
        chunk_cap = max_block_hours * 60
        part = 0
        placed_any = False
        while remaining > 0:
            need = min(remaining, chunk_cap)
            placed = False
            for a, b in _free_windows(ws, we, [(s - 0, e + buffer_min) for s, e in busy]):
                # windows were padded by buffer on the end of busy blocks only
                if b - a >= min(need, 30):
                    length = min(need, b - a)
                    start, end = a, a + int(length)
                    busy.append((start, end))
                    part += 1
                    title = t["title"] + (f" (part {part})" if remaining > chunk_cap or part > 1 else "")
                    why = _reason(t, today_iso)
                    res.slots.append(Slot(t.get("id"), title, tp.from_minutes(start), tp.from_minutes(end), why))
                    remaining -= length
                    placed = placed_any = True
                    break
            if not placed:
                break
        if remaining > 1:
            res.unscheduled.append({"id": t.get("id"), "title": t["title"],
                                    "reason": "No free time left today" if not placed_any else "Only partially fits today"})
    res.slots.sort(key=lambda s: s.start)
    return res


def _reason(task: dict, today_iso: str) -> str:
    bits = [f"{(task.get('priority') or 'medium')} priority"]
    due = task.get("due_date")
    if due:
        days = (_d(due) - _d(today_iso)).days
        bits.append("overdue" if days < 0 else "due today" if days == 0 else f"due in {days}d")
    return ", ".join(bits)


def validate_schedule(slots: list[Slot]) -> list[str]:
    """Return a list of problems (empty list = valid)."""
    problems = []
    ordered = sorted(slots, key=lambda s: tp.to_minutes(s.start))
    for a, b in zip(ordered, ordered[1:]):
        if tp.to_minutes(a.end) > tp.to_minutes(b.start):
            problems.append(f"'{a.title}' ({a.start}-{a.end}) overlaps '{b.title}' ({b.start}-{b.end})")
    for s in ordered:
        if tp.to_minutes(s.end) <= tp.to_minutes(s.start):
            problems.append(f"'{s.title}' has non-positive duration")
    return problems
