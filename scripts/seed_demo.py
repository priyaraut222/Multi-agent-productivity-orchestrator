"""Create a demo account with realistic data so you can show every feature immediately.

    python scripts/seed_demo.py            # user: demo / password: demo12345
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db, repo  # noqa: E402
from core import timeparse as tp  # noqa: E402


def main() -> None:
    db.init_db()
    uid = repo.create_user("demo", "demo12345", "demo@example.com", "Demo User")
    if not uid:
        print("Demo user already exists (demo / demo12345).")
        return
    today = tp.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    repo.add_memory(uid, "I do my best deep work before noon", "preference", 4)
    repo.add_memory(uid, "I prefer short, bullet-style email summaries", "preference", 3)
    repo.add_event(uid, "Team standup", d(0), "10:00", "10:30", meeting_link="https://meet.jit.si/DemoStandup")
    repo.add_event(uid, "Project review", d(0), "15:00", "16:00", attendees="mentor@example.com")
    for title, pr, due, hrs in [("Finish quarterly report", "urgent", d(0), 3), ("Prepare demo slides", "high", d(1), 2),
                                ("Reply to client emails", "medium", d(0), 0.5), ("Fix login bug", "high", d(-2), 2),
                                ("Read research paper", "low", d(5), 1.5), ("Update README", "medium", d(2), 1)]:
        repo.add_task(uid, title, priority=pr, due_date=due, estimated_hours=hrs, scheduled_date=due if due >= d(0) else None)
    from agents import goals
    from core.llm import LLMClient, LLMRouter
    from tools.registry import ToolContext

    plan = goals.propose_plan(ToolContext(user_id=uid, llm=LLMRouter([LLMClient("offline")])), "Ship my capstone project", d(30), 8)
    goals.commit_plan(uid, plan)
    print("Seeded. Log in with  demo / demo12345")


if __name__ == "__main__":
    main()
