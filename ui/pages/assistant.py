import streamlit as st

from agents import orchestrator
from core import repo
from ui import common as C

QUICK = [("🗓️ Plan my day", "Plan my day"), ("📥 Triage my inbox", "Triage my unread emails and turn action items into tasks"),
         ("🔁 Reschedule overdue", "Reschedule my overdue tasks"), ("📊 Weekly review", "Run my weekly review")]


def _history_for_llm(limit: int = 6) -> list[dict]:
    return [{"role": m["role"], "content": m["content"][:600]} for m in repo.list_chat(C.uid(), limit)]


def _handle(prompt: str, fast: bool) -> None:
    history = _history_for_llm()
    repo.add_chat(C.uid(), "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        status = st.status("Agents are working…", expanded=True)

        def on_event(ev):
            status.markdown(C.format_event(ev))

        res = orchestrator.run(C.uid(), prompt, history=history, on_event=on_event, fast=fast)
        status.update(label=f"Done · {res.llm_calls} LLM call(s) · path: {' → '.join(res.path)}", state="complete", expanded=False)
        st.markdown(res.answer)
    repo.add_chat(C.uid(), "assistant", res.answer, res.run_id)
    st.rerun()


def render() -> None:
    st.title("🤖 Agent Assistant")
    st.caption(f"Supervisor → specialist agents → critic · Model: {C.provider_badge()}")
    top1, top2, top3 = st.columns([2, 2, 1])
    fast = top1.toggle("Fast mode (skip critic review)", value=False)
    if top3.button("Clear chat"):
        repo.clear_chat(C.uid())
        st.rerun()
    cols = st.columns(len(QUICK))
    clicked = None
    for col, (label, text) in zip(cols, QUICK):
        if col.button(label, key=f"quick_{label}"):
            clicked = text

    for m in repo.list_chat(C.uid(), 40):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant" and m["run_id"]:
                pend = repo.list_approvals(C.uid(), "pending", run_id=m["run_id"])
                if pend:
                    C.approval_cards(pend, f"chat{m['run_id']}")
                with st.expander("🔍 How the agents did this"):
                    C.render_steps(repo.list_steps(m["run_id"]))

    prompt = st.chat_input("e.g. “Schedule a design review tomorrow 3pm with bob@example.com and add a prep task”") or clicked
    if prompt:
        _handle(prompt, fast)
