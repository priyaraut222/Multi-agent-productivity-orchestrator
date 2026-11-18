import streamlit as st

from core import repo
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("🧠 Agent Memory")
    st.caption("Long-term facts and preferences that every agent receives as context. You are in full control: add, review or delete anything.")
    with st.form("add_mem", clear_on_submit=True):
        c1, c2, c3 = st.columns([4, 1, 1])
        content = c1.text_input("Something the agents should know", placeholder="I do deep work best before noon")
        kind = c2.selectbox("Type", ["preference", "fact", "habit", "lesson"])
        imp = c3.slider("Importance", 1, 5, 3)
        if st.form_submit_button("Save") and content.strip():
            repo.add_memory(uid, content, kind, imp)
            st.rerun()
    mems = repo.list_memories(uid)
    if not mems:
        st.info("No memories yet. They are also created automatically when you say things like “remember…”, “I prefer…”, and by the weekly review.")
    for m in mems:
        a, b = st.columns([8, 1])
        a.markdown(f"<span class='pill'>{m['kind']}</span> {m['content']}", unsafe_allow_html=True)
        if b.button("🗑️", key=f"dm_{m['id']}"):
            repo.delete_memory(m["id"], uid)
            st.rerun()
