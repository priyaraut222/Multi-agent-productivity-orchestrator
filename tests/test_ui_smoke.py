"""Executes every Streamlit page (and app.py) against a fake `streamlit` module to catch NameErrors,
bad SQL, wrong keyword arguments and similar breakage without needing a browser."""
import importlib
import sys
import unittest
from unittest.mock import patch

from tests.helpers import fresh_db, install_fake_streamlit

from core import repo
from core import timeparse as tp

PAGES = ["Dashboard", "Assistant", "Today's Plan", "Workboard", "Goals", "Calendar", "Gmail", "GitHub", "Search",
         "Collaborators", "Approvals", "Memory", "Agent Activity", "Connections", "Settings", "Profile"]


class UISmokeTests(unittest.TestCase):
    def setUp(self):
        self.uid = fresh_db()
        self.st = install_fake_streamlit()
        for mod in [m for m in sys.modules if m.startswith("ui") or m == "app"]:
            del sys.modules[mod]
        self.today = tp.today().isoformat()
        repo.add_task(self.uid, "Write report", priority="high", due_date=self.today, estimated_hours=2, scheduled_date=self.today)
        repo.add_task(self.uid, "Overdue thing", priority="urgent", due_date="2020-01-01")
        done = repo.add_task(self.uid, "Finished", status="done")
        repo.update_task(done, self.uid, status="done")
        repo.add_event(self.uid, "Standup", self.today, "10:00", "10:30", meeting_link="https://meet.jit.si/x")
        g = repo.add_goal(self.uid, "Learn SQL", target_date="2030-01-01")
        repo.add_milestone(g, "Basics", "2030-01-01")
        repo.add_task(self.uid, "SELECT drills", goal_id=g)
        repo.add_memory(self.uid, "I prefer mornings", "preference")
        repo.create_approval(self.uid, "send_email", {"to": "a@b.com", "subject": "s", "body": "b"}, "Send email to a@b.com", "email")
        bob = repo.create_user("bob", "password123", "bob@example.com")
        repo.send_collab_request(bob, self.uid)
        self.st.session_state.update({"authenticated": True, "user": repo.authenticate("alice", "password123"),
                                      "session_token": repo.create_session(self.uid)})

    def _render(self, page):
        self.st.session_state["page"] = page
        if "app" in sys.modules:
            importlib.reload(sys.modules["app"])
        else:
            importlib.import_module("app")

    def test_every_page_renders(self):
        for page in PAGES:
            with self.subTest(page=page):
                self._render(page)

    def test_login_page_renders_when_logged_out(self):
        self.st.session_state.clear()
        self._render("Dashboard")

    def test_assistant_round_trip_and_quick_action(self):
        self.st.session_state["_chat_prompt"] = "add task buy milk tomorrow"
        self._render("Assistant")
        titles = [t["title"] for t in repo.list_tasks(self.uid)]
        self.assertIn("Buy milk", titles)
        self.assertEqual(repo.list_chat(self.uid)[-1]["role"], "assistant")
        self._render("Assistant")                       # re-render with history + inline approvals
        self.st.pressed = {"📊 Weekly review"}
        self.st.session_state["_chat_prompt"] = None
        self._render("Assistant")

    def test_button_flows(self):
        flows = {
            "Today's Plan": {"⚡ Generate plan", "✅ Apply to calendar & tasks", "♻️ Reschedule overdue tasks first"},
            "Approvals": {"✅ Approve", f"inbox_ok_{1}"},
            "Dashboard": {"✨ Ask the AI coach for recommendations", "Review approvals"},
            "Goals": {"🧩 Generate plan", "💾 Save plan"},
            "Memory": {"🗑️"},
            "Agent Activity": set(),
        }
        for page, pressed in flows.items():
            with self.subTest(page=page):
                self.st.pressed = pressed
                if page == "Goals":
                    self.st.session_state["goal"] = "Learn Rust"
                self._render(page)
        plan = repo.get_plan(self.uid, self.today)
        self.assertIsNotNone(plan)

    def test_goal_preview_and_save(self):
        from agents import goals
        from core.llm import LLMClient, LLMRouter
        from tools.registry import ToolContext

        plan = goals.propose_plan(ToolContext(user_id=self.uid, llm=LLMRouter([LLMClient("offline")])), "Learn Rust", "2030-06-01", 5)
        self.st.session_state["goal_plan"] = plan
        self._render("Goals")                                    # preview path
        self.st.pressed = {"💾 Save plan"}
        self._render("Goals")
        self.assertIn("Learn Rust", [g["title"] for g in repo.list_goals(self.uid)])

    def test_connected_gmail_and_github_pages(self):
        mails = [{"id": "1", "subject": "Deadline tomorrow", "sender": "boss", "snippet": "please", "date": "", "link": "l"}]
        gh = type("GH", (), {})()
        gh.repos = lambda limit=20: [{"full_name": "me/app", "name": "app", "owner": "me", "private": False, "description": "", "language": "Py",
                                      "stars": 1, "open_issues": 0, "updated": "2026-01-01T00:00:00Z", "url": "u"}]
        gh.notifications = lambda all_=False, limit=20: [{"id": "n1", "title": "t", "type": "x", "repo": "me/app", "reason": "mention", "unread": True}]
        with patch("integrations.google.is_connected", return_value=True), patch("integrations.google.gmail_read", return_value=mails), \
                patch("integrations.github_api.is_connected", return_value=True), patch("tools.github_tools.get_client", return_value=gh):
            self.st.pressed = {"Fetch emails", "🧠 Triage unread mail", "📌 Make task", "mt_1"}
            self._render("Gmail")
            self._render("Gmail")                                # second pass renders the stored triage result
            self.st.pressed = {"Load my repositories", "Load notifications"}
            self._render("GitHub")
            self._render("GitHub")
        self.assertTrue(any(t["source"] == "gmail" for t in repo.list_tasks(self.uid)))

    def test_approval_button_executes_through_ui(self):
        self.st.pressed = {"inbox_ok_1"}
        with patch("integrations.google.is_connected", return_value=True), patch("integrations.google.gmail_send", return_value="m") as send:
            self._render("Approvals")
        send.assert_called_once()
        self.assertEqual(repo.get_approval(1, self.uid)["status"], "executed")

    def test_oauth_callback_restores_session_and_saves_token(self):
        token = self.st.session_state["session_token"]
        self.st.session_state.clear()                              # simulate the fresh session after the redirect
        self.st.query_params = {"code": "abc", "state": f"github.{token}"}
        with patch("integrations.github_api.exchange_code", return_value="gho_tok"), \
                patch("integrations.github_api.GitHubClient.user", return_value={"login": "alice-gh"}):
            self._render("Dashboard")
        self.assertEqual(repo.get_token(self.uid, "github")["login"], "alice-gh")
        self.assertTrue(self.st.session_state["authenticated"])

    def test_oauth_callback_with_bad_session_is_ignored(self):
        self.st.session_state.clear()
        self.st.query_params = {"code": "abc", "state": "github.forged-token"}
        self._render("Dashboard")
        self.assertFalse(self.st.session_state.get("authenticated"))
        self.assertIsNone(repo.get_token(self.uid, "github"))


if __name__ == "__main__":
    unittest.main()
