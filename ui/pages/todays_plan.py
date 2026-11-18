import streamlit as st

from agents import planner
from core import repo, scheduler
from core import timeparse as tp
from ui import common as C


def _timeline(plan: dict) -> None:
    for s in plan["slots"]:
        cls = "timeline-slot fixed" if s["fixed"] else "timeline-slot"
        why = "Fixed commitment" if s["fixed"] else s.get("reason", "")
        st.markdown(f"<div class='{cls}'><span class='t'>{tp.pretty_time(s['start'])} – {tp.pretty_time(s['end'])}</span> "
                    f"&nbsp; {s['title']}<div class='r'>{why}</div></div>", unsafe_allow_html=True)


def render() -> None:
    uid = C.uid()
    st.title("🗓️ Today's Plan")
    st.caption("The Planner agent ranks tasks by priority and deadline, then a constraint scheduler places them around your meetings — "
               "the result is verified to be overlap-free before you see it.")
    c1, c2, c3 = st.columns(3)
    day = c1.date_input("Date", value=tp.today())
    ws = c2.text_input("Work starts", value=repo.get_setting(uid, "work_start", "09:00"))
    we = c3.text_input("Work ends", value=repo.get_setting(uid, "work_end", "18:00"))
    date = day.isoformat()
    if tp.normalize_time(ws) is None or tp.normalize_time(we) is None:
        st.error("Enter work hours as HH:MM.")
        return
    if st.button("⚡ Generate plan", type="primary"):
        with st.spinner("Planner agent is working…"):
            planner.generate_plan(C.tool_ctx(), date, tp.normalize_time(ws), tp.normalize_time(we))
    plan = repo.get_plan(uid, date)
    if not plan:
        st.info("No plan yet for this date. Click **Generate plan**.")
        return
    st.markdown(f"**{plan['narrative']}**")
    for w in plan.get("warnings", []):
        st.error(w)
    _timeline(plan)
    for u in plan.get("unscheduled", []):
        st.warning(f"Could not fit: **{u['title']}** — {u['reason']}")
    for tip in plan.get("tips", []):
        st.markdown(f"💡 {tip}")
    a, b = st.columns([1, 3])
    if a.button("✅ Apply to calendar & tasks"):
        n = planner.apply_plan(uid, plan)
        st.success(f"Added {n} focus block(s) to your calendar and updated task times.")
    if b.button("♻️ Reschedule overdue tasks first"):
        moves = planner.reschedule_overdue(uid)
        st.success(f"Moved {len(moves)} overdue task(s). Regenerate the plan to include them.")
