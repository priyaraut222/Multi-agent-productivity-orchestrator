"""Small, dependency-light natural-language date/time helpers (used by tools and the offline LLM)."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core import config

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def now() -> datetime:
    try:
        return datetime.now(ZoneInfo(config.TIMEZONE))
    except Exception:  # pragma: no cover
        return datetime.now()


def today() -> date:
    return now().date()


def parse_date(text: str, ref: date | None = None) -> str | None:
    """Return YYYY-MM-DD for phrases like 'tomorrow', 'next friday', 'Jan 14', '14th', '2026-03-02'."""
    if not text:
        return None
    ref = ref or today()
    t = text.lower().strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return m.group(0)
    if "day after tomorrow" in t:
        return (ref + timedelta(days=2)).isoformat()
    if "tomorrow" in t or re.search(r"\btmrw\b", t):
        return (ref + timedelta(days=1)).isoformat()
    if "today" in t or "tonight" in t:
        return ref.isoformat()
    m = re.search(r"in (\d+) days?", t)
    if m:
        return (ref + timedelta(days=int(m.group(1)))).isoformat()
    if "next week" in t:
        return (ref + timedelta(days=7)).isoformat()
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b|\b{name[:3]}\b", t):
            delta = (i - ref.weekday()) % 7
            if delta == 0 or "next" in t:
                delta = delta or 7
            return (ref + timedelta(days=delta)).isoformat()
    # "jan 14", "14 jan", "14th january"
    mon_pat = "|".join(MONTHS)
    m = re.search(rf"\b({mon_pat})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t) or None
    m2 = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({mon_pat})[a-z]*\b", t)
    month = day = None
    if m:
        month, day = MONTHS.index(m.group(1)) + 1, int(m.group(2))
    elif m2:
        month, day = MONTHS.index(m2.group(2)) + 1, int(m2.group(1))
    if month:
        year = ref.year
        try:
            cand = date(year, month, day)
        except ValueError:
            return None
        if cand < ref:
            cand = date(year + 1, month, day)
        return cand.isoformat()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        d = int(m.group(1))
        year, month = ref.year, ref.month
        try:
            cand = date(year, month, d)
        except ValueError:
            return None
        if cand < ref:
            month = month % 12 + 1
            year += 1 if month == 1 else 0
            try:
                cand = date(year, month, d)
            except ValueError:
                return None
        return cand.isoformat()
    return None


_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.I)


def _to_hhmm(h: int, mi: int, ap: str | None) -> str:
    if ap:
        ap = ap.lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    return f"{h:02d}:{mi:02d}"


def parse_times(text: str) -> list[str]:
    """Return all clock times found, as HH:MM (24h)."""
    out = []
    for m in _TIME_RE.finditer(text or ""):
        if m.group(1):
            out.append(_to_hhmm(int(m.group(1)), int(m.group(2) or 0), m.group(3)))
        else:
            out.append(_to_hhmm(int(m.group(4)), int(m.group(5)), None))
    return out


def parse_duration_hours(text: str) -> float | None:
    t = (text or "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", t)
    if m:
        return int(m.group(1)) / 60
    return None


def normalize_time(value: str | None) -> str | None:
    """Accept '4pm', '16:00', '16:00:00' and return HH:MM, or None."""
    if not value:
        return None
    found = parse_times(str(value))
    if found:
        return found[0]
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", str(value).strip())
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def add_hours(hhmm: str, hours: float) -> str:
    h, m = map(int, hhmm.split(":"))
    total = min(h * 60 + m + int(round(hours * 60)), 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":")[:2])
    return h * 60 + m


def from_minutes(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def pretty_time(hhmm: str | None) -> str:
    if not hhmm:
        return ""
    return datetime.strptime(hhmm[:5], "%H:%M").strftime("%I:%M %p").lstrip("0")
