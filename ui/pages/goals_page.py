import streamlit as st

from agents import goals
from core import repo
from core import timeparse as tp
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("🎯 Goals")
    st.caption("Describe an outcome; the Goal Planner agent decomposes it into milestones and tasks. You review the plan before anything is saved.")
    with st.expander("➕ New goal", expanded=not repo.list_goals(uid)):
        goal = st.text_input("Goal", placeholder="Learn SQL well enough to pass a technical interview")
        c1, c2 = st.columns(2)
        target = c1.date_input("Target date", value=None)
        hours = c2.number_input("Hours per week available", 1.0, 80.0, 6.0, 0.5)
        notes = st.text_area("Constraints / preferences (optional)", height=60)
        if st.button("🧩 Generate plan") and goal.strip():
            with st.spinner("Goal Planner agent is decomposing your goal…"):
                st.session_state["goal_plan"] = goals.propose_plan(C.tool_ctx(), goal, target.isoformat() if target else "", hours, notes)
        plan = st.session_state.get("goal_plan")
        if plan:
            st.markdown(f"### {plan['title']}")
            st.caption(f"{plan['summary']}  ·  horizon {plan['horizon_days']} days")
            for m in plan["milestones"]:
                st.markdown(f"**{m['title']}** — in {m['due_in_days']} days")
                st.dataframe([{"task": t["title"], "hours": t["estimated_hours"], "priority": t["priority"]} for t in m["tasks"]])
            a, b = st.columns([1, 4])
            if a.button("💾 Save plan", type="primary"):
                gid = goals.commit_plan(uid, plan)
                st.session_state.pop("goal_plan", None)
                st.success(f"Saved goal #{gid} with its tasks. Find them on the Workboard.")
                st.rerun()
            if b.button("Discard"):
                st.session_state.pop("goal_plan", None)
                st.rerun()

    for g in repo.list_goals(uid):
        with st.container(border=True):
            st.subheader(f"{g['title']}  {'✅' if g['status'] == 'done' else ''}")
            st.progress(min(g["progress"], 1.0), text=f"{g['done_tasks']}/{g['total_tasks']} tasks done · target {g['target_date'] or 'flexible'}")
            for m in repo.list_milestones(g["id"]):
                st.markdown(f"- {'🏁' if m['due_date'] and m['due_date'] < tp.today().isoformat() else '🔹'} {m['title']} — {m['due_date']}")
            a, b, _ = st.columns([1, 1, 4])
            if a.button("♻️ Re-plan overdue", key=f"rp_{g['id']}"):
                moves = goals.replan_goal(uid, g["id"])
                st.success(f"Moved {len(moves)} overdue task(s).")
            if b.button("Mark done" if g["status"] != "done" else "Reopen", key=f"gd_{g['id']}"):
                repo.update_goal(g["id"], uid, status="done" if g["status"] != "done" else "active")
                st.rerun()
