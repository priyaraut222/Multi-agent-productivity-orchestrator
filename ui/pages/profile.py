import streamlit as st

from core import repo, security
from ui import common as C


def render() -> None:
    st.title("👤 Profile")
    u = C.user()
    with st.container(border=True):
        email = st.text_input("Email", value=u.get("email", ""))
        name = st.text_input("Full name", value=u.get("full_name", "") or "")
        if st.button("Save details"):
            if not security.valid_email(email):
                st.error("Enter a valid email.")
            else:
                repo.update_user(u["id"], email, name)
                u["email"], u["full_name"] = email.lower(), name
                st.success("Profile updated.")
    with st.container(border=True):
        st.subheader("Change password")
        p1 = st.text_input("New password", type="password")
        p2 = st.text_input("Confirm", type="password")
        if st.button("Update password"):
            problem = security.password_problem(p1)
            if problem:
                st.error(problem)
            elif p1 != p2:
                st.error("Passwords do not match.")
            else:
                repo.set_password(u["id"], p1)
                st.success("Password changed.")
