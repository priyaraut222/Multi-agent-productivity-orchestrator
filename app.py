"""Multi-Agent Productivity & Goal Orchestration System — Streamlit entry point."""
import streamlit as st

from core import config, db, repo

st.set_page_config(page_title=config.APP_SHORT, page_icon=config.APP_ICON, layout="wide", initial_sidebar_state="expanded")


@st.cache_resource
def _init() -> bool:
    db.init_db()
    return True


_init()

from ui import common as C  # noqa: E402  (after page config)
from ui.pages import (activity, approvals_page, assistant, calendar_page, collaborators, connections, dashboard,  # noqa: E402
                      github_page, gmail_page, goals_page, login, memory_page, profile, search_page, settings_page,
                      todays_plan, workboard)

PAGES = {
    "Dashboard": ("🏠", dashboard.render), "Assistant": ("🤖", assistant.render), "Today's Plan": ("🗓️", todays_plan.render),
    "Workboard": ("🧠", workboard.render), "Goals": ("🎯", goals_page.render), "Calendar": ("📅", calendar_page.render),
    "Gmail": ("📧", gmail_page.render), "GitHub": ("🐙", github_page.render), "Search": ("🔍", search_page.render),
    "Collaborators": ("👥", collaborators.render), "Approvals": ("✅", approvals_page.render), "Memory": ("🧠", memory_page.render),
    "Agent Activity": ("🔭", activity.render), "Connections": ("🔌", connections.render), "Settings": ("⚙️", settings_page.render),
    "Profile": ("👤", profile.render),
}


def handle_oauth_callback() -> None:
    """Google/GitHub redirect back with ?code=...&state=<provider>.<session token>; the token restores the login."""
    qp = st.query_params
    code, state = qp.get("code"), qp.get("state")
    if not code or not state or "." not in state:
        return
    provider, token = state.split(".", 1)
    user = repo.validate_session(token)
    if not user:
        st.query_params.clear()
        return
    st.session_state.update({"user": user, "session_token": token, "authenticated": True})
    try:
        if provider == "github":
            from integrations import github_api

            access = github_api.exchange_code(code)
            login_name = github_api.GitHubClient(access).user().get("login", "")
            repo.save_token(user["id"], "github", {"access_token": access, "login": login_name})
        elif provider in ("google_calendar", "gmail"):
            from integrations import google

            google.finish_auth(provider, code, user["id"])
        st.session_state["flash"] = f"✅ {provider.replace('_', ' ').title()} connected."
    except Exception as exc:
        st.session_state["flash"] = f"⚠️ Connection failed: {exc}"
    st.query_params.clear()
    st.session_state["_nav_request"] = "Connections"


def main() -> None:
    C.load_css()
    handle_oauth_callback()
    if not st.session_state.get("authenticated"):
        login.render()
        return
    if "_nav_request" in st.session_state:
        st.session_state["page"] = st.session_state.pop("_nav_request")
    st.session_state.setdefault("page", "Dashboard")
    pending = len(repo.list_approvals(C.uid(), "pending"))
    with st.sidebar:
        st.markdown(f"### {config.APP_ICON} {config.APP_SHORT}")
        st.caption(f"Signed in as **{C.user()['username']}**")
        st.radio("Navigate", list(PAGES), key="page",
                 format_func=lambda p: f"{PAGES[p][0]} {p}" + (f"  ({pending})" if p == "Approvals" and pending else ""),
                 label_visibility="collapsed")
        st.divider()
        st.caption(f"🧩 {C.provider_badge()}")
        if st.button("Log out"):
            repo.delete_session(st.session_state.get("session_token", ""))
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
    if st.session_state.get("flash"):
        st.toast(st.session_state.pop("flash"))
    PAGES[st.session_state["page"]][1]()


main()
