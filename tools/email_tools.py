"""Gmail tools: read, triage, draft (LLM), send (human-approved), convert emails to tasks."""
from __future__ import annotations

import re

from core import repo
from core import timeparse as tp
from integrations import google
from tools._util import ask_llm, ask_llm_json, fail
from tools.registry import Tool, ToolContext, register

P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731
NOT_CONNECTED = "Gmail is not connected. Open Authorization and connect Gmail first."
URGENT_WORDS = re.compile(r"urgent|asap|deadline|due|overdue|action required|invoice|payment|expires|final notice", re.I)
MEETING_WORDS = re.compile(r"meeting|invite|calendar|schedule|call", re.I)


def read_emails(ctx: ToolContext, query: str = "", limit: int = 5) -> dict:
    if not google.is_connected(ctx.user_id, "gmail"):
        return fail(NOT_CONNECTED)
    try:
        mails = google.gmail_read(ctx.user_id, query, min(int(limit), 20))
    except Exception as exc:
        return fail(f"Failed to read emails: {exc}")
    return {"emails": mails, "count": len(mails), "message": f"Found {len(mails)} email(s)" + (f" for '{query}'." if query else ".")}


def send_email(ctx: ToolContext, to: str, subject: str, body: str) -> dict:
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to or ""):
        return fail(f"'{to}' is not a valid email address.")
    if not google.is_connected(ctx.user_id, "gmail"):
        return fail(NOT_CONNECTED)
    try:
        mid = google.gmail_send(ctx.user_id, to, subject, body)
    except Exception as exc:
        return fail(f"Failed to send email: {exc}")
    return {"message_id": mid, "message": f"✅ Email sent to {to}."}


def draft_email(ctx: ToolContext, to: str, intent: str, tone: str = "professional", context: str = "") -> dict:
    user = repo.get_user(ctx.user_id) or {}
    sys = ("You write concise, clear emails. Reply as JSON: {\"subject\": str, \"body\": str}. "
           f"Tone: {tone}. Sign off with the sender's name: {user.get('full_name') or user.get('username', '')}.")
    data = ask_llm_json(ctx, sys, f"Recipient: {to}\nGoal: {intent}\nContext: {context}", role="writer")
    if not isinstance(data, dict) or "body" not in data:
        data = {"subject": intent[:60].capitalize(), "body": f"Hi,\n\n{intent.strip().capitalize()}.\n\nBest regards,\n{user.get('full_name') or user.get('username', '')}"}
    return {"draft": data, "message": "Draft ready (not sent). Use send_email to send it after approval."}


def triage_inbox(ctx: ToolContext, query: str = "is:unread", limit: int = 10) -> dict:
    res = read_emails(ctx, query, limit)
    if res.get("ok") is False:
        return res
    mails = res["emails"]
    labelled = ask_llm_json(
        ctx, 'Classify each email. Return JSON {"items":[{"id":str,"label":"urgent|action|meeting|fyi|ignore","reason":str}]}.',
        "\n".join(f"{m['id']} | {m['sender']} | {m['subject']} | {m['snippet'][:120]}" for m in mails), role="writer")
    by_id = {i.get("id"): i for i in (labelled or {}).get("items", [])} if isinstance(labelled, dict) else {}
    for m in mails:
        item = by_id.get(m["id"])
        if item:
            m["label"], m["reason"] = item.get("label", "fyi"), item.get("reason", "")
        else:  # heuristic fallback (works offline)
            text = f"{m['subject']} {m['snippet']}"
            m["label"] = "urgent" if URGENT_WORDS.search(text) else "meeting" if MEETING_WORDS.search(text) else "fyi"
            m["reason"] = "keyword heuristic"
    counts = {}
    for m in mails:
        counts[m["label"]] = counts.get(m["label"], 0) + 1
    return {"emails": mails, "counts": counts, "message": "Inbox triage: " + ", ".join(f"{v} {k}" for k, v in counts.items())}


def email_to_task(ctx: ToolContext, subject: str, sender: str = "", snippet: str = "", priority: str = "medium", due_date: str = "") -> dict:
    tid = repo.add_task(ctx.user_id, f"Reply/act: {subject}"[:120], description=f"From {sender}\n{snippet}", priority=priority,
                        due_date=due_date or None, source="gmail", estimated_hours=0.5)
    return {"task_id": tid, "message": f"📌 Created task #{tid} from email '{subject}'."}


register(Tool("read_emails", "Read/search Gmail (supports from:, subject:, is:unread).", {
    "query": P("string", "Gmail search query"), "limit": P("integer", "max emails")}, read_emails, "email", "read"))
register(Tool("send_email", "Send an email via Gmail (requires human approval).", {
    "to": P("string", "recipient", True), "subject": P("string", "subject", True), "body": P("string", "plain-text body", True)},
    send_email, "email", "external", lambda a: f"Send email to {a.get('to')} — subject: {a.get('subject')}"))
register(Tool("draft_email", "Compose an email draft with the LLM WITHOUT sending it.", {
    "to": P("string", "recipient", True), "intent": P("string", "what the email should achieve", True),
    "tone": P("string", "professional|friendly|brief"), "context": P("string", "extra facts")}, draft_email, "email", "read"))
register(Tool("triage_inbox", "Classify recent emails into urgent/action/meeting/fyi/ignore.", {
    "query": P("string", "Gmail query, default is:unread"), "limit": P("integer", "max")}, triage_inbox, "email", "read"))
register(Tool("email_to_task", "Turn an email into a workboard task.", {
    "subject": P("string", "", True), "sender": P("string", ""), "snippet": P("string", ""), "priority": P("string", ""),
    "due_date": P("string", "YYYY-MM-DD")}, email_to_task, "email", "write"))
