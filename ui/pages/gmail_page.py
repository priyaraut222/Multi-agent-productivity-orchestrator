import streamlit as st

from integrations import google
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("📧 Gmail")
    if not google.is_connected(uid, "gmail"):
        st.warning("Gmail is not connected yet. Go to **Connections** to authorise it (free Google OAuth).")
        if st.button("Open Connections"):
            C.goto("Connections")
        st.caption("You can still use the **Compose with AI** tab to prepare drafts.")
    tab_inbox, tab_triage, tab_compose = st.tabs(["Inbox", "AI triage", "Compose with AI"])
    with tab_inbox:
        q = st.text_input("Search (Gmail syntax)", value="is:inbox", key="mail_q")
        n = st.slider("How many", 1, 20, 5)
        if st.button("Fetch emails"):
            res = C.run_tool("read_emails", query=q, limit=n)
            if res.get("ok"):
                for m in res["emails"]:
                    with st.container(border=True):
                        st.markdown(f"**{m['subject']}**  \n{m['sender']} · {m['date']}")
                        st.caption(m["snippet"])
                        st.markdown(f"[Open in Gmail]({m['link']})")
                if not res["emails"]:
                    st.info("No emails found.")
            else:
                C.show_result(res)
    with tab_triage:
        st.caption("The Email agent classifies unread mail (urgent / action / meeting / FYI) and can turn action emails into tasks.")
        if st.button("🧠 Triage unread mail"):
            res = C.run_tool("triage_inbox", query="is:unread", limit=10)
            st.session_state["triage"] = res
        res = st.session_state.get("triage")
        if res:
            if not res.get("ok"):
                C.show_result(res)
            else:
                st.info(res["message"])
                for m in res["emails"]:
                    with st.container(border=True):
                        st.markdown(f"**[{m['label'].upper()}]** {m['subject']} — {m['sender']}")
                        st.caption(m.get("reason", ""))
                        if m["label"] in ("urgent", "action", "meeting") and st.button("📌 Make task", key=f"mt_{m['id']}"):
                            C.show_result(C.run_tool("email_to_task", subject=m["subject"], sender=m["sender"], snippet=m["snippet"],
                                                     priority="high" if m["label"] == "urgent" else "medium"))
    with tab_compose:
        to = st.text_input("To")
        intent = st.text_area("What should the email achieve?", height=80)
        tone = st.selectbox("Tone", ["professional", "friendly", "brief", "formal"])
        if st.button("✍️ Draft with AI") and to and intent:
            st.session_state["draft"] = C.run_tool("draft_email", to=to, intent=intent, tone=tone)["draft"]
        draft = st.session_state.get("draft")
        if draft:
            subj = st.text_input("Subject", value=draft["subject"])
            body = st.text_area("Body", value=draft["body"], height=220)
            if st.button("📤 Send (needs your approval)"):
                C.show_result(C.run_tool("send_email", to=to, subject=subj, body=body))
