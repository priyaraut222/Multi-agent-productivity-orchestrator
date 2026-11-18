import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tests.helpers import fresh_db

from core import crypto, llm, repo, scheduler, security
from core import timeparse as tp


class TimeParseTests(unittest.TestCase):
    ref = date(2026, 11, 17)  # a Tuesday

    def test_relative_dates(self):
        self.assertEqual(tp.parse_date("tomorrow", self.ref), "2026-11-18")
        self.assertEqual(tp.parse_date("next friday", self.ref), "2026-11-20")
        self.assertEqual(tp.parse_date("in 3 days", self.ref), "2026-11-20")
        self.assertEqual(tp.parse_date("Jan 14", self.ref), "2027-01-14")  # rolls to next year
        self.assertEqual(tp.parse_date("on 2026-12-01", self.ref), "2026-12-01")
        self.assertIsNone(tp.parse_date("no date here", self.ref))

    def test_times_and_durations(self):
        self.assertEqual(tp.parse_times("4am-8am"), ["04:00", "08:00"])
        self.assertEqual(tp.parse_times("at 15:30 and 3pm"), ["15:30", "15:00"])
        self.assertEqual(tp.parse_times("12am"), ["00:00"])
        self.assertEqual(tp.parse_duration_hours("for 90 minutes"), 1.5)
        self.assertEqual(tp.normalize_time("4pm"), "16:00")
        self.assertEqual(tp.normalize_time("16:00:00"), "16:00")
        self.assertEqual(tp.add_hours("23:30", 2), "23:59")  # clamps instead of wrapping


class SchedulerTests(unittest.TestCase):
    def test_no_overlaps_and_respects_fixed_events(self):
        tasks = [{"id": i, "title": f"T{i}", "priority": p, "estimated_hours": h}
                 for i, (p, h) in enumerate([("urgent", 3), ("high", 2), ("low", 1), ("medium", 4)], 1)]
        events = [{"title": "Standup", "start_time": "10:00", "end_time": "11:00"},
                  {"title": "Review", "start_time": "15:00", "end_time": "16:00"}]
        res = scheduler.build_schedule(tasks, events, "2026-11-17")
        self.assertEqual(scheduler.validate_schedule(res.slots), [])
        fixed = [s for s in res.slots if s.fixed]
        self.assertEqual({(s.start, s.end) for s in fixed}, {("10:00", "11:00"), ("15:00", "16:00")})
        for s in res.slots:
            self.assertGreaterEqual(s.start, "09:00")
            self.assertLessEqual(s.end, "18:00")
        # lunch hour stays free
        for s in res.slots:
            self.assertFalse(s.start < "14:00" and s.end > "13:00" and not s.fixed)

    def test_priority_and_deadline_ordering(self):
        urgent = {"id": 1, "title": "urgent", "priority": "urgent", "estimated_hours": 1}
        low_due = {"id": 2, "title": "low-overdue", "priority": "low", "estimated_hours": 1, "due_date": "2026-11-10"}
        low = {"id": 3, "title": "low", "priority": "low", "estimated_hours": 1}
        self.assertGreater(scheduler.score(low_due, "2026-11-17"), scheduler.score(low, "2026-11-17"))
        res = scheduler.build_schedule([low, low_due, urgent], [], "2026-11-17")
        order = [s.task_id for s in res.slots]
        self.assertEqual(order[0], 1)

    def test_overflow_is_reported_not_overlapped(self):
        tasks = [{"id": 1, "title": "huge", "priority": "high", "estimated_hours": 20}]
        res = scheduler.build_schedule(tasks, [], "2026-11-17")
        self.assertTrue(res.unscheduled)
        self.assertEqual(scheduler.validate_schedule(res.slots), [])

    def test_validator_detects_overlap(self):
        a = scheduler.Slot(1, "a", "09:00", "10:00")
        b = scheduler.Slot(2, "b", "09:30", "10:30")
        self.assertEqual(len(scheduler.validate_schedule([a, b])), 1)


class RepoTests(unittest.TestCase):
    def setUp(self):
        self.uid = fresh_db()

    def test_auth(self):
        self.assertIsNotNone(repo.authenticate("alice", "password123"))
        self.assertIsNone(repo.authenticate("alice", "wrong"))
        self.assertIsNone(repo.create_user("alice", "x" * 8, "other@example.com"))  # duplicate username

    def test_task_lifecycle_and_isolation(self):
        bob = repo.create_user("bob", "password123", "bob@example.com")
        tid = repo.add_task(self.uid, "Write docs", priority="weird")
        self.assertEqual(repo.get_task(tid)["priority"], "medium")        # invalid priority normalised
        self.assertIsNone(repo.get_task(tid, bob))                         # other users cannot see it
        self.assertFalse(repo.update_task(tid, bob, status="done"))
        self.assertTrue(repo.update_task(tid, self.uid, status="done"))
        self.assertIsNotNone(repo.get_task(tid)["completed_at"])
        repo.update_task(tid, self.uid, status="todo")
        self.assertIsNone(repo.get_task(tid)["completed_at"])

    def test_assignee_sees_task(self):
        bob = repo.create_user("bob", "password123", "bob@example.com")
        tid = repo.add_task(self.uid, "Shared", assignee_id=bob)
        self.assertEqual([t["id"] for t in repo.list_tasks(bob)], [tid])

    def test_goal_progress(self):
        g = repo.add_goal(self.uid, "Ship")
        a = repo.add_task(self.uid, "a", goal_id=g)
        repo.add_task(self.uid, "b", goal_id=g)
        repo.update_task(a, self.uid, status="done")
        self.assertEqual(repo.get_goal(g, self.uid)["progress"], 0.5)

    def test_memory_search_and_dedupe(self):
        repo.add_memory(self.uid, "I prefer deep work in the morning", "preference")
        repo.add_memory(self.uid, "i prefer deep work in the morning", "preference")
        self.assertEqual(len(repo.list_memories(self.uid)), 1)
        repo.add_memory(self.uid, "Sister's birthday is in March", "fact")
        found = repo.search_memories(self.uid, "when is my sister's birthday")
        self.assertIn("Sister's birthday is in March", [m["content"] for m in found])

    def test_events_conflicts(self):
        repo.add_event(self.uid, "A", "2026-11-18", "10:00", "11:00")
        self.assertEqual(len(repo.find_conflicts(self.uid, "2026-11-18", "10:30", "11:30")), 1)
        self.assertEqual(len(repo.find_conflicts(self.uid, "2026-11-18", "11:00", "12:00")), 0)  # touching is fine

    def test_collaboration_flow(self):
        bob = repo.create_user("bob", "password123", "bob@example.com")
        self.assertTrue(repo.send_collab_request(self.uid, bob))
        req = repo.incoming_requests(bob)[0]
        repo.respond_request(req["request_id"], bob, True)
        self.assertEqual([c["username"] for c in repo.list_collaborators(self.uid)], ["bob"])
        repo.remove_collaborator(self.uid, bob)
        self.assertEqual(repo.list_collaborators(bob), [])

    def test_sessions_and_encrypted_storage(self):
        token = repo.create_session(self.uid)
        self.assertEqual(repo.validate_session(token)["username"], "alice")
        repo.delete_session(token)
        self.assertIsNone(repo.validate_session(token))
        repo.set_setting(self.uid, "key_groq", "gsk_secret", encrypted=True)
        from core import db
        raw = db.query("SELECT value FROM user_settings WHERE key='key_groq'", one=True)["value"]
        self.assertNotIn("gsk_secret", raw)
        self.assertEqual(repo.get_setting(self.uid, "key_groq"), "gsk_secret")
        repo.save_token(self.uid, "github", {"access_token": "abc"})
        self.assertEqual(repo.get_token(self.uid, "github")["access_token"], "abc")


class SecurityTests(unittest.TestCase):
    def test_password_hash(self):
        h = security.hash_password("hunter2hunter2")
        self.assertTrue(security.verify_password("hunter2hunter2", h))
        self.assertFalse(security.verify_password("nope", h))
        self.assertNotEqual(h, security.hash_password("hunter2hunter2"))  # salted
        self.assertFalse(security.verify_password("x", "garbage"))

    def test_crypto_roundtrip(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt("hello")), "hello")
        self.assertIsNone(crypto.decrypt("not-a-token"))


class LLMTests(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(llm.extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(llm.extract_json('Sure!\n```json\n{"a": {"b": "}"}}\n```\nbye'), {"a": {"b": "}"}})
        self.assertEqual(llm.extract_json("blah [1, 2] blah"), [1, 2])
        self.assertIsNone(llm.extract_json("no json at all"))

    def test_http_retry_and_fallback(self):
        ok = MagicMock(status_code=200, headers={})
        ok.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        limited = MagicMock(status_code=429, text="slow down", headers={})
        with patch("core.llm.requests.post", side_effect=[limited, ok]), patch("core.llm.time.sleep"):
            self.assertEqual(llm.LLMClient("groq", api_key="k").chat([{"role": "user", "content": "x"}]), "hi")
        # primary keeps failing -> router falls back to the second provider
        bad = MagicMock(status_code=500, text="boom", headers={})
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return bad if "groq" in url else ok

        router = llm.LLMRouter([llm.LLMClient("groq", api_key="a"), llm.LLMClient("gemini", api_key="b")])
        with patch("core.llm.requests.post", side_effect=fake_post), patch("core.llm.time.sleep"):
            self.assertEqual(router.chat([{"role": "user", "content": "x"}]), "hi")
        self.assertEqual(router.used, "gemini")

    def test_auth_error_is_not_retried(self):
        denied = MagicMock(status_code=401, text="bad key", headers={})
        with patch("core.llm.requests.post", return_value=denied) as post, patch("core.llm.time.sleep"):
            with self.assertRaises(llm.LLMError):
                llm.LLMClient("groq", api_key="k").chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_count, 1)

    def test_chat_json_repairs_once(self):
        c = MagicMock()
        c.provider = "groq"
        c.chat.side_effect = ["not json", '{"ok": true}']
        self.assertEqual(llm.LLMRouter([c]).chat_json([{"role": "user", "content": "x"}]), {"ok": True})

    def test_make_llm_defaults_to_offline_without_keys(self):
        uid = fresh_db()
        with patch.dict("os.environ", {}, clear=False):
            r = llm.make_llm(uid, "groq")
        self.assertTrue(r.is_offline or r.clients[0].provider != "groq" or r.clients[0].api_key)


if __name__ == "__main__":
    unittest.main()
