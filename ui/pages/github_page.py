import streamlit as st

from integrations import github_api
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("🐙 GitHub")
    if not github_api.is_connected(uid):
        st.warning("GitHub is not connected. Add a free personal access token (or OAuth app) in **Connections**.")
        if st.button("Open Connections"):
            C.goto("Connections")
        return
    tab_repos, tab_issues, tab_prs, tab_notif, tab_new = st.tabs(["Repositories", "Issues", "Pull requests", "Notifications", "New repository"])
    with tab_repos:
        if st.button("Load my repositories"):
            st.session_state["gh_repos"] = C.run_tool("list_repositories", limit=30)
        res = st.session_state.get("gh_repos")
        if res and res.get("ok"):
            st.dataframe([{"repo": r["full_name"], "language": r["language"], "★": r["stars"], "open issues": r["open_issues"],
                           "private": r["private"], "updated": r["updated"][:10]} for r in res["repositories"]])
            pick = st.selectbox("Summarise a repository (AI)", [r["full_name"] for r in res["repositories"]])
            if st.button("Summarise"):
                o, n = pick.split("/")
                with st.spinner("Reading repo…"):
                    r = C.run_tool("summarize_repository", owner=o, repo=n)
                st.markdown(r.get("summary") or r.get("error"))
        elif res:
            C.show_result(res)
    with tab_issues:
        c1, c2, c3 = st.columns([2, 2, 1])
        owner, name = c1.text_input("Owner", key="gi_o"), c2.text_input("Repository", key="gi_r")
        if c3.button("Load issues") and owner and name:
            st.session_state["gh_issues"] = (owner, name, C.run_tool("list_issues", owner=owner, repo=name))
        data = st.session_state.get("gh_issues")
        if data:
            o, n, res = data
            if res.get("ok"):
                for i in res["issues"]:
                    st.markdown(f"[#{i['number']}]({i['url']}) **{i['title']}** — {i['author']} {' '.join('`'+l+'`' for l in i['labels'])}")
                if res["issues"] and st.button("📥 Import open issues as tasks"):
                    C.show_result(C.run_tool("issues_to_tasks", owner=o, repo=n))
            else:
                C.show_result(res)
        with st.expander("Create an issue (needs approval)"):
            t = st.text_input("Title", key="ni_t")
            b = st.text_area("Body", key="ni_b", height=80)
            if st.button("Submit issue") and owner and name and t:
                C.show_result(C.run_tool("create_issue", owner=owner, repo=name, title=t, body=b))
    with tab_prs:
        c1, c2, c3 = st.columns([2, 2, 1])
        po, pn = c1.text_input("Owner", key="gp_o"), c2.text_input("Repository", key="gp_r")
        if c3.button("Load PRs") and po and pn:
            st.session_state["gh_prs"] = (po, pn, C.run_tool("list_pull_requests", owner=po, repo=pn))
        data = st.session_state.get("gh_prs")
        if data:
            o, n, res = data
            if res.get("ok"):
                for p in res["pull_requests"]:
                    a, b = st.columns([5, 1])
                    a.markdown(f"[#{p['number']}]({p['url']}) **{p['title']}** — {p['author']}")
                    if b.button("AI review", key=f"pr_{p['number']}"):
                        st.markdown(C.run_tool("summarize_pull_request", owner=o, repo=n, pr_number=p["number"]).get("summary", ""))
            else:
                C.show_result(res)
    with tab_notif:
        if st.button("Load notifications"):
            st.session_state["gh_notif"] = C.run_tool("read_notifications")
        res = st.session_state.get("gh_notif")
        if res and res.get("ok"):
            for n in res["notifications"]:
                a, b = st.columns([5, 1])
                a.markdown(f"🔔 {n['title']} _({n['reason']})_")
                if b.button("Mark read", key=f"nr_{n['id']}"):
                    C.show_result(C.run_tool("mark_notification_as_read", notification_id=n["id"]))
        elif res:
            C.show_result(res)
    with tab_new:
        name = st.text_input("Repository name")
        desc = st.text_input("Description")
        ptype = st.selectbox("Project type", ["empty", "python", "node", "java", "go", "rust", "web"])
        private = st.checkbox("Private")
        if st.button("Create (needs approval)") and name:
            C.show_result(C.run_tool("create_repository", name=name, description=desc, private=private, project_type=ptype))
