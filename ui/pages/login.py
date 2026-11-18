import streamlit as st

from core import config, repo, security


def _start_session(user: dict) -> None:
    st.session_state["user"] = user
    st.session_state["session_token"] = repo.create_session(user["id"])
    st.session_state["authenticated"] = True


def render() -> None:
    st.title(f"{config.APP_ICON} {config.APP_SHORT}")
    st.caption(config.APP_NAME)
    st.markdown("A team of specialised AI agents that plan your goals, schedule your time, triage your inbox, "
                "track your GitHub work and research the web — with you approving every external action. **100% free stack.**")
    tab_login, tab_signup = st.tabs(["Log in", "Create account"])
    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in"):
                user = repo.authenticate(username, password)
                if user:
                    _start_session(user)
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    with tab_signup:
        with st.form("signup_form"):
            new_user = st.text_input("Username")
            full_name = st.text_input("Full name")
            email = st.text_input("Email")
            new_pass = st.text_input("Password (min 8 characters)", type="password")
            if st.form_submit_button("Create account"):
                problem = (None if new_user.strip() else "Username is required.") or \
                          (None if security.valid_email(email) else "Enter a valid email.") or security.password_problem(new_pass)
                if problem:
                    st.error(problem)
                elif repo.create_user(new_user, new_pass, email, full_name):
                    st.success("Account created — you can log in now.")
                else:
                    st.error("That username or email is already taken.")
