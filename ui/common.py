"""Shared Streamlit helpers."""
from __future__ import annotations

import json

import streamlit as st

from core import config, repo
from core.llm import make_llm
from tools import loader
from tools import registry as R

loader.load()

PRIORITY_ICON = {"urgent": "🔴", "high": "🟠", "medium": "🔵", "low": "⚪"}
KIND_ICON = {"thought": "💭", "tool_call": "🛠️", "observation": "👁️", "route": "🧭", "start": "▶️", "final": "✅",
             "verdict": "🧪", "revise": "✍️", "recall": "🧠", "write": "💾", "error": "⚠️"}


def load_css() -> None:
    try:
        with open(config.BASE_DIR / "styles" / "main.css") as fh:
            st.markdown(f"<style>{fh.read()}</style>", unsafe_allow_html=True)
    except OSError:
        pass


def user() -> dict:
    return st.session_state["user"]


def uid() -> int:
    return int(st.session_state["user"]["id"])


def goto(page: str) -> None:
    st.session_state["_nav_request"] = page
    st.rerun()


def llm():
    return make_llm(uid())


def autonomy() -> str:
    return repo.get_setting(uid(), "autonomy", "ask_external")


def tool_ctx() -> R.ToolContext:
    return R.ToolContext(user_id=uid(), llm=llm(), autonomy=autonomy(), username=user()["username"], agent="ui")


def run_tool(name: str, **args) -> dict:
    """Invoke a tool from the UI exactly like an agent would (so approvals and validation still apply)."""
    return R.execute(name, args, tool_ctx())


def show_result(res: dict, success_prefix: str = "") -> None:
    if res.get("status") == "pending_approval":
        st.info(res["message"] + " — see **Approvals**.")
    elif res.get("ok"):
        st.success(success_prefix + (res.get("message") or "Done."))
    else:
        st.error(res.get("error") or "Something went wrong.")
        if res.get("free_slots"):
            st.caption("Free slots: " + ", ".join(s["title"] for s in res["free_slots"]))


def format_event(ev: dict) -> str:
    c, kind, agent = ev["content"], ev["kind"], ev["agent"]
    icon = KIND_ICON.get(kind, "•")
    if kind == "route":
        steps = c.get("steps", [])
        body = " → ".join(f"**{s['agent']}**" for s in steps) if steps else "answer directly"
    elif kind == "tool_call":
        body = f"`{c['tool']}` {json.dumps(c['args'], default=str)[:160]}"
    elif kind == "observation":
        body = f"`{c['tool']}` → {'ok' if c.get('ok') else 'failed'}" + (f" ({c.get('status')})" if c.get("status") else "") + f": {str(c.get('message'))[:140]}"
    elif kind == "verdict":
        body = c["verdict"] + (": " + "; ".join(c["issues"]) if c.get("issues") else "")
    elif isinstance(c, (dict, list)):
        body = json.dumps(c, default=str)[:200]
    else:
        body = str(c)[:240]
    return f"{icon} **{agent}** · {kind} — {body}"


def render_steps(steps: list[dict]) -> None:
    for ev in steps:
        st.markdown(format_event(ev))


def approval_cards(approvals: list[dict], prefix: str) -> None:
    for a in approvals:
        with st.container(border=True):
            st.markdown(f"**{a['agent'] or 'agent'}** wants to: {a['summary']}")
            with st.expander("Exact arguments"):
                st.json(a["args"])
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("✅ Approve", key=f"{prefix}_ok_{a['id']}"):
                res = R.run_approved(a["id"], uid(), llm())
                (st.toast("Executed ✔ " + str(res.get("message", ""))[:120]) if res.get("ok") else st.toast("Failed: " + str(res.get("error"))[:140]))
                st.rerun()
            if c2.button("❌ Reject", key=f"{prefix}_no_{a['id']}"):
                R.reject(a["id"], uid())
                st.rerun()


def provider_badge() -> str:
    router = llm()
    first = router.clients[0]
    spec = config.PROVIDERS[first.provider]
    return f"{spec['label']} · {first.model}" if first.provider != "offline" else "Offline demo mode"
