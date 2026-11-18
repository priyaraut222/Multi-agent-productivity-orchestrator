import streamlit as st

from core import config, repo
from integrations import github_api, google
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("🔌 Connections")
    st.caption("All integrations use free tiers. Tokens are stored encrypted. Everything works without them except the service itself.")
    token = st.session_state.get("session_token", "")
    st.subheader("Google (Calendar & Gmail)")
    if not google.is_configured():
        st.info("To enable: create a free OAuth client in Google Cloud Console (type *Web*, redirect URI "
                f"`{config.REDIRECT_URI}`), then set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`. See README → Setup.")
    for provider, label in [("google_calendar", "Google Calendar"), ("gmail", "Gmail")]:
        c1, c2 = st.columns([3, 1])
        if google.is_connected(uid, provider):
            c1.success(f"{label}: connected")
            if c2.button("Disconnect", key=f"dc_{provider}"):
                repo.delete_token(uid, provider)
                st.rerun()
        else:
            c1.warning(f"{label}: not connected")
            if google.is_configured():
                c2.link_button("Connect", google.auth_url(provider, token))
    st.subheader("GitHub")
    gh = repo.get_token(uid, "github")
    if github_api.is_connected(uid):
        c1, c2 = st.columns([3, 1])
        c1.success("GitHub: connected" + (f" as {gh.get('login')}" if gh and gh.get("login") else " (token from environment)"))
        if gh and c2.button("Disconnect", key="dc_gh"):
            repo.delete_token(uid, "github")
            st.rerun()
    else:
        st.warning("GitHub: not connected")
    if github_api.oauth_configured():
        st.link_button("Connect with GitHub OAuth", github_api.auth_url(token))
    with st.expander("Or use a personal access token (simplest, free)"):
        st.caption("GitHub → Settings → Developer settings → Personal access tokens. Scopes: `repo`, `notifications`.")
        pat = st.text_input("Token", type="password", key="pat")
        if st.button("Save token") and pat:
            try:
                login = github_api.GitHubClient(pat.strip()).user()["login"]
                repo.save_token(uid, "github", {"access_token": pat.strip(), "login": login})
                st.success(f"Connected as {login}")
                st.rerun()
            except Exception as exc:
                st.error(f"Token rejected: {exc}")
