import streamlit as st

from core import repo
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("👥 Collaborators")
    tab_team, tab_add, tab_req = st.tabs(["My team", "Find people", "Requests"])
    with tab_team:
        team = repo.list_collaborators(uid)
        if not team:
            st.info("You have no collaborators yet.")
        for c in team:
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{c['username']}** · {c['email']}" + (f" · {c['full_name']}" if c["full_name"] else ""))
                if b.button("Remove", key=f"rm_{c['id']}"):
                    repo.remove_collaborator(uid, c["id"])
                    st.rerun()
        st.caption("Collaborators can be invited to meetings and assigned tasks (Workboard → Assign to).")
    with tab_add:
        term = st.text_input("Search by username or email")
        team_ids = {c["id"] for c in repo.list_collaborators(uid)}
        for r in repo.search_users(uid, term) if term else []:
            a, b = st.columns([4, 1])
            a.markdown(f"**{r['username']}** · {r['email']}")
            if r["id"] in team_ids:
                b.success("Added")
            elif b.button("Add", key=f"add_{r['id']}"):
                st.toast("Request sent!" if repo.send_collab_request(uid, r["id"]) else "Request already exists.")
    with tab_req:
        reqs = repo.incoming_requests(uid)
        if not reqs:
            st.info("No pending requests.")
        for r in reqs:
            a, b, c = st.columns([4, 1, 1])
            a.markdown(f"**{r['username']}** ({r['email']}) wants to collaborate")
            if b.button("Accept", key=f"acc_{r['request_id']}"):
                repo.respond_request(r["request_id"], uid, True)
                st.rerun()
            if c.button("Reject", key=f"rej_{r['request_id']}"):
                repo.respond_request(r["request_id"], uid, False)
                st.rerun()
