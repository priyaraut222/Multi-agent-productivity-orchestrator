import json
import unittest
from unittest.mock import patch

from tests.helpers import ScriptedRouter, fresh_db

from agents import goals, insights, orchestrator, planner
from agents.graph import END, GraphError, StateGraph
from core import repo
from core import timeparse as tp
from tools import registry as R
from tools.registry import ToolContext


def J(**kw):
    return json.dumps(kw)


class GraphTests(unittest.TestCase):
    def test_loop_and_conditional_routing(self):
        g = StateGraph("t")
        g.add_node("inc", lambda s: {"n": s["n"] + 1}).add_node("done", lambda s: {"finished": True})
        g.set_entry("inc").add_conditional_edges("inc", lambda s: "inc" if s["n"] < 3 else "done", ["inc", "done"]).add_edge("done", END)
        out = g.compile().run({"n": 0})
        self.assertEqual((out["n"], out["finished"]), (3, True))
        self.assertEqual(out["_path"], ["inc", "inc", "inc", "done"])

    def test_validation_and_recursion_limit(self):
        g = StateGraph("t").add_node("a", lambda s: None).set_entry("a")
        with self.assertRaises(GraphError):
            g.compile()                       # no outgoing edge
        g.add_edge("a", "a")
        with self.assertRaises(GraphError):
            g.compile().run({}, recursion_limit=5)
        self.assertIn("digraph", g.to_dot())


class OfflineOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.uid = fresh_db()

    def test_task_calendar_conflict_flow(self):
        r = orchestrator.run(self.uid, "add task finish report tomorrow 3pm urgent for 2 hours")
        self.assertIn("Added task", r.answer)
        t = repo.list_tasks(self.uid)[0]
        self.assertEqual((t["priority"], t["start_time"], t["end_time"], t["estimated_hours"]), ("urgent", "15:00", "17:00", 2.0))
        orchestrator.run(self.uid, "schedule a meeting tomorrow 4pm-5pm about launch")
        r = orchestrator.run(self.uid, "schedule a meeting tomorrow 4:30pm-5:30pm about review")
        self.assertIn("conflict", r.answer.lower())
        self.assertEqual(len(repo.list_events(self.uid, tp.parse_date("tomorrow"))), 1)  # no double booking

    def test_trace_is_persisted(self):
        r = orchestrator.run(self.uid, "show my tasks")
        kinds = [s["kind"] for s in repo.list_steps(r.run_id)]
        for k in ("recall", "route", "tool_call", "observation", "verdict", "final"):
            self.assertIn(k, kinds)
        self.assertEqual(repo.list_runs(self.uid)[0]["status"], "ok")

    def test_greeting_needs_no_agent(self):
        r = orchestrator.run(self.uid, "hi")
        self.assertEqual(r.path, ["recall", "supervise", "finalize"])

    def test_memory_written_from_preference(self):
        orchestrator.run(self.uid, "remember that I prefer deep work in the morning")
        self.assertTrue(any("deep work" in m["content"] for m in repo.list_memories(self.uid)))

    def test_external_action_requires_approval_then_executes(self):
        r = orchestrator.run(self.uid, "send an email to bob@example.com about launch")
        self.assertEqual(len(r.pending), 1)
        self.assertIn("approval", r.answer.lower())
        aid = r.pending[0]["approval_id"]
        with patch("integrations.google.is_connected", return_value=True), patch("integrations.google.gmail_send", return_value="m1") as send:
            res = R.run_approved(aid, self.uid)
        self.assertTrue(res["ok"])
        send.assert_called_once()
        self.assertEqual(repo.get_approval(aid, self.uid)["status"], "executed")
        self.assertFalse(R.run_approved(aid, self.uid)["ok"])           # an approval can never be replayed

    def test_rejected_action_never_runs(self):
        r = orchestrator.run(self.uid, "send an email to bob@example.com about launch")
        aid = r.pending[0]["approval_id"]
        R.reject(aid, self.uid)
        with patch("integrations.google.gmail_send") as send:
            self.assertFalse(R.run_approved(aid, self.uid)["ok"])
        send.assert_not_called()

    def test_goal_plan_creates_tasks(self):
        r = orchestrator.run(self.uid, "I want to learn machine learning by Jan 14")
        self.assertIn("Created goal", r.answer)
        g = repo.list_goals(self.uid)[0]
        self.assertGreaterEqual(g["total_tasks"], 6)
        self.assertTrue(repo.list_milestones(g["id"]))

    def test_users_are_isolated(self):
        bob = repo.create_user("bob", "password123", "bob@example.com")
        orchestrator.run(self.uid, "add task secret plan")
        r = orchestrator.run(bob, "show my tasks")
        self.assertNotIn("secret", r.answer.lower())


class ReActLoopTests(unittest.TestCase):
    """Runs the real supervisor/worker/critic loop against a scripted LLM."""

    def setUp(self):
        self.uid = fresh_db()

    def test_multi_step_plan_with_synthesis_and_critic_pass(self):
        llm = ScriptedRouter({
            "supervisor": [J(steps=[{"agent": "tasks", "task": "create task Prepare slides due 2026-11-20 priority high"},
                                    {"agent": "calendar", "task": "schedule meeting Review on 2026-11-19 at 10:00 for 1 hour"}], direct_answer=None)],
            "tasks": [J(thought="create", action="create_task", args={"title": "Prepare slides", "due_date": "2026-11-20", "priority": "high"}),
                      J(final="Created the task.")],
            "calendar": [J(thought="book", action="schedule_meeting", args={"title": "Review", "date": "2026-11-19", "start_time": "10:00", "duration_hours": 1}),
                         J(final="Booked the review.")],
            "synthesizer": ["I created **Prepare slides** (due Nov 20) and booked the Review on Nov 19 at 10:00."],
            "critic": [J(verdict="pass", issues=[], feedback="")],
        })
        r = orchestrator.run(self.uid, "prep slides and book a review", llm=llm)
        self.assertEqual(r.path, ["recall", "supervise", "execute", "execute", "critic", "finalize"])
        self.assertIn("Prepare slides", r.answer)
        self.assertEqual(len(repo.list_events(self.uid, "2026-11-19")), 1)
        self.assertEqual(repo.list_tasks(self.uid)[0]["title"], "Prepare slides")

    def test_critic_forces_revision_when_claim_is_ungrounded(self):
        llm = ScriptedRouter({
            "supervisor": [J(steps=[{"agent": "email", "task": "email Bob"}], direct_answer=None)],
            "email": [J(final="I have sent the email to Bob.")],          # no tool call at all -> a lie
            "synthesizer": ["I haven't sent anything yet: no email tool call was made. Want me to draft it?"],
        })
        r = orchestrator.run(self.uid, "email Bob", llm=llm)
        self.assertTrue(r.revised)
        self.assertIn("haven't sent", r.answer)
        self.assertIn("revise", [s["kind"] for s in repo.list_steps(r.run_id)])

    def test_ungrounded_claim_detector(self):
        from agents.base import AgentResult
        res = [AgentResult("tasks", "t", "x", tool_calls=[{"tool": "list_tasks", "args": {}, "result": {"ok": True}}])]
        self.assertTrue(orchestrator.grounding_issues("Done, I created it.", res))        # only a read tool ran
        self.assertEqual(orchestrator.grounding_issues("You have 2 tasks added today.", res), [])  # descriptive, not a claim
        none = [AgentResult("tasks", "t", "x")]
        self.assertTrue(orchestrator.grounding_issues("I have sent the email.", none))
        failed = [AgentResult("email", "t", "x", tool_calls=[{"tool": "send_email", "args": {}, "result": {"ok": False, "error": "Gmail is not connected"}}])]
        self.assertTrue(orchestrator.grounding_issues("All good, your email is on its way!", failed))
        self.assertFalse(orchestrator.grounding_issues("It failed: Gmail is not connected.", failed))

    def test_bad_tool_name_and_duplicate_calls_are_recovered(self):
        llm = ScriptedRouter({
            "supervisor": [J(steps=[{"agent": "tasks", "task": "x"}], direct_answer=None)],
            "tasks": [J(action="delete_universe", args={}),                     # hallucinated tool
                      J(action="list_tasks", args={}), J(action="list_tasks", args={}),   # duplicate
                      J(final="You have no open tasks.")],
        })
        r = orchestrator.run(self.uid, "x", llm=llm, fast=True)
        obs = [s["content"] for s in repo.list_steps(r.run_id) if s["kind"] == "observation"]
        self.assertTrue(any("not available" in str(o["message"]) for o in obs))
        self.assertIn("no open tasks", r.answer)

    def test_malformed_supervisor_output_falls_back_safely(self):
        llm = ScriptedRouter({"supervisor": ["garbage", "still garbage"],
                              "tasks": [J(final="ok")]})
        r = orchestrator.run(self.uid, "do something", llm=llm, fast=True)
        self.assertEqual(r.plan[0]["agent"], "tasks")

    def test_provider_outage_gives_honest_message(self):
        from core.llm import LLMError

        class Down(ScriptedRouter):
            def chat(self, *a, **k):
                raise LLMError("all providers failed")

        r = orchestrator.run(self.uid, "hello there", llm=Down({}))
        self.assertIn("couldn't reach", r.answer)

    def test_autonomy_modes(self):
        for mode, expect_pending in (("ask_all", True), ("ask_external", False), ("auto", False)):
            repo.set_setting(self.uid, "autonomy", mode)
            llm = ScriptedRouter({"supervisor": [J(steps=[{"agent": "tasks", "task": "add"}], direct_answer=None)],
                                  "tasks": [J(action="create_task", args={"title": f"t-{mode}"}), J(final="ok")]})
            r = orchestrator.run(self.uid, "add", llm=llm, fast=True)
            self.assertEqual(bool(r.pending), expect_pending, mode)

    def test_arg_validation_and_coercion(self):
        ctx = ToolContext(user_id=self.uid, autonomy="auto")
        self.assertFalse(R.execute("create_task", {}, ctx)["ok"])                       # missing title
        res = R.execute("create_task", {"title": "x", "estimated_hours": "2.5", "bogus": 1}, ctx)  # string->float, unknown dropped
        self.assertTrue(res["ok"])
        self.assertEqual(repo.get_task(res["task_id"])["estimated_hours"], 2.5)
        self.assertFalse(R.execute("nope", {}, ctx)["ok"])


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.uid = fresh_db()
        self.ctx = ToolContext(user_id=self.uid, llm=ScriptedRouter({}), autonomy="auto")
        self.ctx.llm.clients = []

    def _offline_ctx(self):
        from core.llm import LLMClient, LLMRouter
        return ToolContext(user_id=self.uid, llm=LLMRouter([LLMClient("offline")]), autonomy="auto")

    def test_daily_plan_respects_meetings_and_is_valid(self):
        day = "2030-01-15"
        repo.add_event(self.uid, "Standup", day, "10:00", "10:30")
        for i, (p, h) in enumerate([("urgent", 2), ("high", 3), ("medium", 1.5), ("low", 1)]):
            repo.add_task(self.uid, f"T{i}", priority=p, estimated_hours=h, scheduled_date=day)
        plan = planner.generate_plan(self._offline_ctx(), day)
        self.assertEqual(plan["warnings"], [])
        self.assertTrue(any(s["fixed"] and s["title"] == "Standup" for s in plan["slots"]))
        self.assertEqual(repo.get_plan(self.uid, day)["date"], day)

    def test_apply_is_idempotent(self):
        day = "2030-01-15"
        tid = repo.add_task(self.uid, "Deep work", priority="high", estimated_hours=2, scheduled_date=day)
        plan = planner.generate_plan(self._offline_ctx(), day)
        n1 = planner.apply_plan(self.uid, plan)
        n2 = planner.apply_plan(self.uid, plan)
        self.assertEqual(n1, n2)
        self.assertEqual(len([e for e in repo.list_events(self.uid, day) if e["event_type"] == "focus"]), n1)
        self.assertIsNotNone(repo.get_task(tid)["start_time"])
        # regenerating after applying must not treat its own focus blocks as fixed commitments
        plan2 = planner.generate_plan(self._offline_ctx(), day)
        self.assertFalse(any(s["fixed"] for s in plan2["slots"]))

    def test_reschedule_overdue_skips_weekends(self):
        repo.add_task(self.uid, "late", due_date="2020-01-01", priority="high", estimated_hours=2)
        repo.add_task(self.uid, "later", due_date="2020-01-02", estimated_hours=5)
        moves = planner.reschedule_overdue(self.uid)
        self.assertEqual(len(moves), 2)
        from datetime import date
        for m in moves:
            self.assertLess(date.fromisoformat(m["new_due"]).weekday(), 5)
            self.assertGreaterEqual(m["new_due"], tp.today().isoformat())

    def test_insights_metrics_and_rules(self):
        repo.add_task(self.uid, "late", due_date="2020-01-01")
        done = repo.add_task(self.uid, "done")
        repo.update_task(done, self.uid, status="done")
        m = insights.compute_metrics(self.uid)
        self.assertEqual((m["overdue"], m["done_7d"], m["streak"]), (1, 1, 1))
        self.assertTrue(any("overdue" in i["text"] for i in insights.rule_insights(m)))


class GoalTests(unittest.TestCase):
    def test_validate_plan_repairs_bad_llm_output(self):
        bad = {"title": "G", "milestones": [{"title": "M2", "due_in_days": 999, "tasks": [{"title": "t", "estimated_hours": "abc", "priority": "???"}]},
                                            {"title": "M1", "due_in_days": 3, "tasks": [{"title": "u", "estimated_hours": 100}]},
                                            {"title": "empty", "tasks": []}, "junk"]}
        plan = goals.validate_plan(bad, horizon_days=30)
        self.assertEqual([m["title"] for m in plan["milestones"]], ["M1", "M2"])       # sorted, empty/junk dropped
        self.assertEqual(plan["milestones"][1]["due_in_days"], 30)                     # clamped to horizon
        self.assertEqual(plan["milestones"][0]["tasks"][0]["estimated_hours"], 8.0)
        self.assertEqual(plan["milestones"][1]["tasks"][0]["priority"], "medium")
        self.assertIsNone(goals.validate_plan({"milestones": []}, 30))

    def test_llm_plan_used_when_valid_and_fallback_otherwise(self):
        uid = fresh_db()
        good = J(title="Learn SQL", summary="s", milestones=[{"title": "Basics", "due_in_days": 7, "tasks": [{"title": "SELECT drills", "estimated_hours": 2, "priority": "high"}]}])
        ctx = ToolContext(user_id=uid, llm=ScriptedRouter({"writer": [good]}))
        plan = goals.propose_plan(ctx, "Learn SQL", "2030-02-01", 5)
        self.assertEqual(plan["milestones"][0]["title"], "Basics")
        ctx = ToolContext(user_id=uid, llm=ScriptedRouter({"writer": ["nonsense", "nonsense"]}))
        self.assertGreaterEqual(len(goals.propose_plan(ctx, "Learn SQL", "2030-02-01", 5)["milestones"]), 3)

    def test_replan_goal_moves_only_overdue(self):
        uid = fresh_db()
        g = repo.add_goal(uid, "G")
        late = repo.add_task(uid, "late", goal_id=g, due_date="2020-01-01")
        ok = repo.add_task(uid, "future", goal_id=g, due_date="2099-01-01")
        moves = goals.replan_goal(uid, g)
        self.assertEqual([m["id"] for m in moves], [late])
        self.assertEqual(repo.get_task(ok)["due_date"], "2099-01-01")


if __name__ == "__main__":
    unittest.main()
