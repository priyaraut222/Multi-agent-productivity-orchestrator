from datetime import timedelta

import streamlit as st

from core import repo
from core import timeparse as tp
from integrations import google
from tools.calendar_tools import sync_google
from ui import common as C


def _month_widget(events: list[dict]) -> bool:
    """Optional rich month view (pip install streamlit-calendar); falls back silently to the agenda list."""
    try:
        from streamlit_calendar import calendar as st_calendar
    except ImportError:
        return False
    items = [{"title": e["title"], "start": f"{e['date']}T{e['start_time']}" if e["start_time"] else e["date"],
              "end": f"{e['date']}T{e['end_time']}" if e["end_time"] else None} for e in events]
    st_calendar(events=items, options={"initialView": "dayGridMonth", "height": 520})
    return True


def render() -> None:
    uid = C.uid()
    st.title("📅 Calendar")
    connected = google.is_connected(uid, "google_calendar")
    st.caption("Google Calendar: " + ("✅ connected (events sync both ways)" if connected else "not connected — using the built-in local calendar (works fully offline)"))
    c1, c2, c3 = st.columns([2, 2, 1])
    start = c1.date_input("From", value=tp.today())
    end = c2.date_input("To", value=tp.today() + timedelta(days=14))
    if connected and c3.button("🔄 Sync Google"):
        try:
            n = sync_google(uid, start.isoformat(), end.isoformat())
            st.success(f"Imported {n} new event(s) from Google Calendar.")
        except Exception as exc:
            st.error(f"Sync failed: {exc}")
    events = repo.list_events(uid, start.isoformat(), end.isoformat())

    tab_agenda, tab_month, tab_add = st.tabs(["Agenda", "Month view", "Add event"])
    with tab_agenda:
        if not events:
            st.info("No events in this range.")
        day = None
        for e in events:
            if e["date"] != day:
                day = e["date"]
                st.markdown(f"#### {day}")
            with st.container(border=True):
                a, b = st.columns([5, 1])
                span = f"{tp.pretty_time(e['start_time'])} – {tp.pretty_time(e['end_time'])}" if e["start_time"] else "All day"
                a.markdown(f"**{e['title']}** · {span} · _{e['event_type']}_")
                if e.get("attendees"):
                    a.caption("👥 " + e["attendees"])
                if e.get("meeting_link"):
                    a.markdown(f"[🔗 Join meeting]({e['meeting_link']})")
                if b.button("Delete", key=f"delev_{e['id']}"):
                    C.show_result(C.run_tool("delete_event", event_id=e["id"]))
                    st.rerun()
    with tab_month:
        if not _month_widget(events):
            st.info("Install the optional `streamlit-calendar` package for a month grid. The Agenda tab shows the same data.")
    with tab_add:
        with st.form("add_event", clear_on_submit=False):
            title = st.text_input("Title")
            d = st.date_input("Date", value=tp.today(), key="ev_date")
            t1, t2 = st.columns(2)
            s_time = t1.time_input("Start", value=None)
            e_time = t2.time_input("End", value=None)
            attendees = st.text_input("Attendees (emails or collaborator usernames, comma-separated)")
            desc = st.text_area("Description", height=60)
            if st.form_submit_button("Schedule") and title.strip() and s_time:
                C.show_result(C.run_tool("schedule_meeting", title=title, date=d.isoformat(), start_time=s_time.strftime("%H:%M"),
                                         end_time=e_time.strftime("%H:%M") if e_time else "", attendees=attendees, description=desc))
        st.caption("Conflicts are detected automatically and free slots are suggested. Events with attendees need your approval (invites are external).")
