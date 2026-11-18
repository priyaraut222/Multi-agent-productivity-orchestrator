import streamlit as st

from core import repo
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("✅ Approvals")
    st.caption("Human-in-the-loop: agents can *propose* external actions (emails, GitHub writes, invites) but only you can release them.")
    pending = repo.list_approvals(uid, "pending")
    if not pending:
        st.success("Nothing is waiting for approval.")
    C.approval_cards(pending, "inbox")
    st.subheader("History")
    hist = [a for a in repo.list_approvals(uid, None, limit=50) if a["status"] != "pending"]
    if hist:
        st.dataframe([{"id": a["id"], "agent": a["agent"], "action": a["summary"], "status": a["status"], "resolved": a["resolved_at"]} for a in hist])
    else:
        st.caption("No resolved approvals yet.")
