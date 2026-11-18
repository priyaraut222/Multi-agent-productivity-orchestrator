from datetime import timedelta

import streamlit as st

from core import repo
from core import timeparse as tp
from ui import common as C

COLUMNS = [("todo", "📝 To do"), ("in_progress", "🚧 In progress"), ("blocked", "⛔ Blocked"), ("done", "✅ Done")]


def _card(t: dict, collabs: dict) -> None:
    with st.container(border=True):
        st.markdown(f"{C.PRIORITY_ICON.get(t['priority'], '•')} **{t['title']}**")
        meta = []
        if t.get("due_date"):
            meta.append(f"due {t['due_date']}")
        if t.get("scheduled_date") and t.get("start_time"):
            meta.append(f"{t['scheduled_date']} {t['start_time']}")
        if t.get("estimated_hours"):
            meta.append(f"{t['estimated_hours']}h")
        if t.get("assignee_id") and t["assignee_id"] in collabs:
            meta.append(f"→ {collabs[t['assignee_id']]}")
        if t.get("source") and t["source"] != "manual":
            meta.append(t["source"])
        if meta:
            st.caption(" · ".join(meta))
        statuses = [s for s, _ in COLUMNS if s != t["status"]]
        pick = st.selectbox("Move", ["—"] + statuses, key=f"mv_{t['id']}", label_visibility="collapsed")
        if pick != "—":
            repo.update_task(t["id"], C.uid(), status=pick)
            st.rerun()
        if st.button("🗑️", key=f"del_{t['id']}", help="Delete"):
            repo.delete_task(t["id"], C.uid())
            st.rerun()


def render() -> None:
    uid = C.uid()
    st.title("🧠 Workboard")
    collab_list = repo.list_collaborators(uid)
    collabs = {c["id"]: c["username"] for c in collab_list}
    with st.expander("➕ Add task", expanded=False):
        with st.form("add_task", clear_on_submit=True):
            title = st.text_input("Title")
            c1, c2, c3, c4 = st.columns(4)
            priority = c1.selectbox("Priority", ["medium", "low", "high", "urgent"])
            due = c2.date_input("Due date", value=None)
            hours = c3.number_input("Estimate (h)", 0.25, 40.0, 1.0, 0.25)
            assignee = c4.selectbox("Assign to", ["me"] + [c["username"] for c in collab_list])
            desc = st.text_area("Description", height=70)
            if st.form_submit_button("Add") and title.strip():
                assignee_id = next((c["id"] for c in collab_list if c["username"] == assignee), None)
                repo.add_task(uid, title, description=desc, priority=priority, due_date=due.isoformat() if due else None,
                              estimated_hours=hours, assignee_id=assignee_id)
                st.rerun()

    f1, f2, f3 = st.columns(3)
    prio = f1.selectbox("Priority filter", ["All", "urgent", "high", "medium", "low"])
    when = f2.selectbox("Due filter", ["All", "Overdue", "Today", "This week"])
    goals = {g["id"]: g["title"] for g in repo.list_goals(uid)}
    goal = f3.selectbox("Goal", ["All"] + list(goals.values()))
    today = tp.today()
    rows = repo.list_tasks(uid)
    out = []
    for t in rows:
        if prio != "All" and t["priority"] != prio:
            continue
        due = t.get("due_date")
        if when == "Overdue" and not (due and due < today.isoformat() and t["status"] != "done"):
            continue
        if when == "Today" and due != today.isoformat():
            continue
        if when == "This week" and not (due and today.isoformat() <= due <= (today + timedelta(days=7)).isoformat()):
            continue
        if goal != "All" and goals.get(t.get("goal_id")) != goal:
            continue
        out.append(t)
    if not out:
        st.info("No tasks match. Add one above or ask the Assistant.")
    cols = st.columns(4)
    for col, (status, label) in zip(cols, COLUMNS):
        items = [t for t in out if t["status"] == status]
        with col:
            st.subheader(f"{label} ({len(items)})")
            for t in (items[:25] if status == "done" else items):
                _card(t, collabs)

    st.subheader("📅 Upcoming meetings")
    evs = [e for e in repo.list_events(uid, today.isoformat(), (today + timedelta(days=14)).isoformat()) if e["event_type"] == "meeting"]
    if not evs:
        st.caption("No meetings in the next 14 days.")
    for e in evs:
        st.markdown(f"📅 **{e['title']}** — {e['date']} {e['start_time'] or ''}-{e['end_time'] or ''}" + (f" · [join]({e['meeting_link']})" if e.get("meeting_link") else ""))
