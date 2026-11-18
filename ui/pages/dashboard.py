from datetime import timedelta

import streamlit as st

from agents import insights
from core import repo
from core import timeparse as tp
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title(f"👋 Welcome back, {C.user().get('full_name') or C.user()['username']}")
    m = insights.compute_metrics(uid)
    c = st.columns(5)
    c[0].metric("Open tasks", m["open"])
    c[1].metric("Overdue", m["overdue"], delta=None if not m["overdue"] else f"-{m['overdue']}", delta_color="inverse")
    c[2].metric("Done (7 days)", m["done_7d"])
    c[3].metric("Today's load", f"{m['today_load_hours']} h")
    c[4].metric("Streak", f"{m['streak']} 🔥")

    pend = repo.list_approvals(uid, "pending")
    if pend:
        st.warning(f"⏳ {len(pend)} agent action(s) are waiting for your approval.")
        if st.button("Review approvals"):
            C.goto("Approvals")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("💡 Insights")
        for i in insights.rule_insights(m):
            {"warning": st.warning, "success": st.success}.get(i["level"], st.info)(i["text"])
        if st.button("✨ Ask the AI coach for recommendations"):
            with st.spinner("Thinking…"):
                text = insights.ai_narrative(C.tool_ctx(), m)
            st.markdown(text or "_Connect a free LLM provider in **Settings** to enable AI recommendations._")
        st.subheader("📈 Tasks completed (14 days)")
        today = tp.today()
        done = [t for t in repo.list_tasks(uid) if t["status"] == "done" and t.get("completed_at")]
        counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(13, -1, -1)}
        for t in done:
            d = t["completed_at"][:10]
            if d in counts:
                counts[d] += 1
        st.bar_chart(counts)
    with right:
        st.subheader("📅 Today")
        events = repo.list_events(uid, today.isoformat())
        tasks = [t for t in repo.list_tasks(uid, open_only=True) if t.get("scheduled_date") == today.isoformat() or t.get("due_date") == today.isoformat()]
        if not events and not tasks:
            st.caption("Nothing scheduled. Try “Plan my day” in the Assistant.")
        for e in events:
            st.markdown(f"🕒 **{tp.pretty_time(e['start_time']) or 'All day'}** — {e['title']}" + (f"  [join]({e['meeting_link']})" if e.get("meeting_link") else ""))
        for t in tasks:
            st.markdown(f"{C.PRIORITY_ICON.get(t['priority'], '•')} {t['title']}")
        st.subheader("🎯 Goals")
        goals = repo.list_goals(uid, "active")
        if not goals:
            st.caption("No goals yet — create one in **Goals**.")
        for g in goals[:5]:
            st.markdown(f"**{g['title']}** — {g['done_tasks']}/{g['total_tasks']} tasks")
            st.progress(min(g["progress"], 1.0))
