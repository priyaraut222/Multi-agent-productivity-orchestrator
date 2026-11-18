import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import fresh_db

from core import repo
from integrations import search
from tools import loader
from tools import registry as R
from tools.registry import ToolContext

loader.load()


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.uid = fresh_db()
        self.ctx = ToolContext(user_id=self.uid, autonomy="auto")

    def run_tool(self, tool, **args):
        return R.execute(tool, args, self.ctx)

    def test_every_tool_has_valid_metadata(self):
        self.assertGreaterEqual(len(R.REGISTRY), 45)
        for t in R.REGISTRY.values():
            self.assertTrue(t.description and t.group, t.name)
            self.assertIn(t.risk_for({}) if not callable(t.risk) else t.risk({}), ("read", "write", "external"))
            self.assertIn(t.name, t.prompt_line())

    def test_all_original_features_are_covered(self):
        """Parity with the original app's TOOLS.md (names normalised)."""
        original = ["add_task_to_calendar", "get_collaborators", "add_collaborators_to_event", "generate_meeting_link", "schedule_meeting",
                    "get_calendar_events", "send_email", "read_emails", "github_is_connected", "list_repositories", "get_repository_details",
                    "get_repo_structure", "read_file", "summarize_repository", "create_repository", "list_issues", "create_issue", "close_issue",
                    "list_pull_requests", "summarize_pull_request", "comment_on_pull_request", "read_notifications", "mark_notification_as_read",
                    "search_web", "search_images", "search_news", "create_task"]
        for name in original:
            self.assertIn(name, R.REGISTRY, name)

    def test_task_tools(self):
        t = self.run_tool("create_task", title="Fix bug", priority="URGENT", due_date="2026-12-01")
        self.assertTrue(t["ok"])
        self.assertEqual(repo.get_task(t["task_id"])["priority"], "urgent")
        self.assertTrue(self.run_tool("complete_task", title="fix bug")["ok"])
        self.assertFalse(self.run_tool("complete_task", title="fix bug")["ok"])         # already done -> not found
        self.run_tool("create_task", title="Report A")
        self.run_tool("create_task", title="Report B")
        amb = self.run_tool("complete_task", title="Report")
        self.assertFalse(amb["ok"])
        self.assertIn("Several tasks match", amb["error"])                                # never guesses

    def test_assign_only_to_collaborators(self):
        bob = repo.create_user("bob", "password123", "bob@example.com")
        tid = self.run_tool("create_task", title="Shared")["task_id"]
        self.assertFalse(self.run_tool("assign_task", task_id=tid, collaborator="bob")["ok"])
        repo.send_collab_request(self.uid, bob)
        repo.respond_request(repo.incoming_requests(bob)[0]["request_id"], bob, True)
        self.assertTrue(self.run_tool("assign_task", task_id=tid, collaborator="bob")["ok"])
        self.assertEqual(repo.get_task(tid)["assignee_id"], bob)

    def test_calendar_conflict_suggests_free_slots_and_meeting_link(self):
        ok = self.run_tool("schedule_meeting", title="Sync", date="2030-03-01", start_time="10:00", end_time="11:00")
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["meeting_link"].startswith("https://meet.jit.si/"))       # free link, no account needed
        bad = self.run_tool("schedule_meeting", title="Clash", date="2030-03-01", start_time="10:30", end_time="11:30")
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["free_slots"])
        forced = self.run_tool("schedule_meeting", title="Clash", date="2030-03-01", start_time="10:30", end_time="11:30", allow_conflict=True)
        self.assertTrue(forced["ok"])
        self.assertFalse(self.run_tool("schedule_meeting", title="x", date="March", start_time="10:00")["ok"])
        self.assertFalse(self.run_tool("schedule_meeting", title="x", date="2030-03-01", start_time="10:00", end_time="09:00")["ok"])

    def test_attendees_make_meetings_external(self):
        self.ctx.autonomy = "ask_external"
        res = self.run_tool("schedule_meeting", title="Invite", date="2030-03-02", start_time="09:00", attendees="x@y.com")
        self.assertEqual(res["status"], "pending_approval")
        self.assertEqual(repo.list_events(self.uid, "2030-03-02"), [])                 # nothing happened yet
        solo = self.run_tool("schedule_meeting", title="Solo", date="2030-03-02", start_time="09:00")
        self.assertTrue(solo["ok"])

    def test_google_events_are_imported_once(self):
        from tools.calendar_tools import sync_google
        g = [{"google_event_id": "g1", "title": "From Google", "date": "2030-03-03", "start_time": "09:00", "end_time": "10:00",
              "meeting_link": "", "description": "", "attendees": ""}]
        with patch("integrations.google.is_connected", return_value=True), patch("integrations.google.calendar_list_events", return_value=g):
            self.assertEqual(sync_google(self.uid, "2030-03-03", "2030-03-03"), 1)
            self.assertEqual(sync_google(self.uid, "2030-03-03", "2030-03-03"), 0)

    def test_email_tools_validate_and_report_not_connected(self):
        self.assertFalse(self.run_tool("send_email", to="not-an-email", subject="s", body="b")["ok"])
        res = self.run_tool("send_email", to="a@b.com", subject="s", body="b")
        self.assertFalse(res["ok"])
        self.assertIn("not connected", res["error"])
        draft = self.run_tool("draft_email", to="a@b.com", intent="ask for a deadline extension")
        self.assertIn("body", draft["draft"])
        self.assertTrue(self.run_tool("email_to_task", subject="Invoice due")["ok"])

    def test_inbox_triage_heuristics_offline(self):
        mails = [{"id": "1", "subject": "URGENT: invoice overdue", "sender": "a", "snippet": "", "date": "", "link": ""},
                 {"id": "2", "subject": "Newsletter", "sender": "b", "snippet": "tips", "date": "", "link": ""}]
        with patch("integrations.google.is_connected", return_value=True), patch("integrations.google.gmail_read", return_value=mails):
            res = self.run_tool("triage_inbox")
        self.assertEqual([m["label"] for m in res["emails"]], ["urgent", "fyi"])

    def _gh(self):
        gh = MagicMock()
        gh.repos.return_value = [{"full_name": "me/app", "name": "app", "owner": "me", "private": False, "description": "", "language": "Python",
                                  "stars": 1, "open_issues": 2, "updated": "2026-01-01T00:00:00Z", "url": "u"}]
        gh.issues.return_value = [{"number": 7, "title": "Crash on start", "state": "open", "author": "x", "labels": ["bug"], "url": "u7", "body": "trace"}]
        gh.create_issue.return_value = {"number": 8, "url": "u8"}
        gh.create_repo.return_value = {"full_name": "me/new", "url": "u", "clone": "c.git", "default_branch": "main"}
        gh.enable_pages.return_value = "https://me.github.io/new/"
        return gh

    def test_github_read_tools_and_issue_import(self):
        gh = self._gh()
        with patch("tools.github_tools.get_client", return_value=gh):
            self.assertEqual(self.run_tool("list_repositories")["count"], 1)
            self.assertEqual(self.run_tool("issues_to_tasks", owner="me", repo="app")["imported"], 1)
            self.assertEqual(self.run_tool("issues_to_tasks", owner="me", repo="app")["imported"], 0)     # idempotent
        t = repo.list_tasks(self.uid)[0]
        self.assertEqual((t["priority"], t["source"]), ("high", "github"))                              # bug label -> high

    def test_github_writes_need_approval_and_not_connected_is_clean(self):
        self.ctx.autonomy = "ask_external"
        gh = self._gh()
        with patch("tools.github_tools.get_client", return_value=gh):
            res = self.run_tool("create_issue", owner="me", repo="app", title="Bug")
            self.assertEqual(res["status"], "pending_approval")
            gh.create_issue.assert_not_called()
            out = R.run_approved(res["approval_id"], self.uid)
            self.assertTrue(out["ok"])
            gh.create_issue.assert_called_once()
            res = self.run_tool("create_repository", name="new", files={"index.html": "<h1>hi</h1>"}, enable_pages=True)
            ok = R.run_approved(res["approval_id"], self.uid)
        self.assertIn("github.io", ok["message"])
        gh.put_file.assert_called_once()
        self.assertFalse(R.execute("list_repositories", {}, ToolContext(user_id=self.uid, autonomy="auto"))["ok"])  # no token -> clear error

    def test_search_wrappers_clamp_and_handle_errors(self):
        with patch("integrations.search._run", return_value={"ok": True, "rows": [{"title": "T", "href": "http://x", "body": "b"}]}) as run:
            res = self.run_tool("search_web", query="python", limit=999)
        self.assertEqual(run.call_args[0][2], 10)
        self.assertEqual(res["results"][0]["url"], "http://x")
        with patch("integrations.search._run", return_value={"ok": False, "error": "offline"}):
            self.assertFalse(self.run_tool("search_news", query="x")["ok"])
        self.assertFalse(search.fetch_page("ftp://nope")["ok"])

    def test_fetch_page_strips_markup(self):
        resp = MagicMock(text="<html><title>Hi</title><script>evil()</script><p>Hello <b>world</b></p></html>")
        resp.raise_for_status.return_value = None
        with patch("integrations.search.requests.get", return_value=resp):
            out = search.fetch_page("https://example.com")
        self.assertEqual(out["title"], "Hi")
        self.assertNotIn("evil", out["text"])
        self.assertIn("Hello world", out["text"])

    def test_memory_tools(self):
        self.run_tool("remember", content="Prefers email summaries on Fridays", kind="preference")
        self.assertEqual(self.run_tool("recall", query="email summaries")["count"], 1)


if __name__ == "__main__":
    unittest.main()
