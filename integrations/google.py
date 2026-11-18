"""Google OAuth + Calendar + Gmail (free APIs). Tokens are stored encrypted per user."""
from __future__ import annotations

import base64
import os
from email.mime.text import MIMEText

from core import config, repo

SCOPES = {
    "google_calendar": ["https://www.googleapis.com/auth/calendar"],
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
}


class NotConnected(RuntimeError):
    pass


def is_configured() -> bool:
    return bool((config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET) or os.path.exists(config.GOOGLE_CLIENT_SECRETS_FILE))


def _client_config() -> dict:
    if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
        return {"web": {"client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [config.REDIRECT_URI]}}
    import json

    with open(config.GOOGLE_CLIENT_SECRETS_FILE) as fh:
        return json.load(fh)


def _flow(provider: str):
    from google_auth_oauthlib.flow import Flow

    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES[provider], autogenerate_code_verifier=False)
    flow.redirect_uri = config.REDIRECT_URI
    return flow


def auth_url(provider: str, session_token: str) -> str:
    """The state carries provider + the app session token so login survives the Google redirect."""
    url, _ = _flow(provider).authorization_url(prompt="consent", access_type="offline",
                                               state=f"{provider}.{session_token}")
    return url


def finish_auth(provider: str, code: str, user_id: int) -> None:
    flow = _flow(provider)
    flow.fetch_token(code=code)
    c = flow.credentials
    repo.save_token(user_id, provider, {"token": c.token, "refresh_token": c.refresh_token, "token_uri": c.token_uri,
                                        "client_id": c.client_id, "client_secret": c.client_secret,
                                        "scopes": list(c.scopes or SCOPES[provider])})


def is_connected(user_id: int, provider: str) -> bool:
    return repo.get_token(user_id, provider) is not None


def _credentials(user_id: int, provider: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    data = repo.get_token(user_id, provider)
    if not data:
        raise NotConnected(f"{provider} is not connected. Open the Authorization page to connect it.")
    creds = Credentials(**data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data["token"] = creds.token
        repo.save_token(user_id, provider, data)
    return creds


def _service(user_id: int, provider: str, api: str, version: str):
    from googleapiclient.discovery import build

    return build(api, version, credentials=_credentials(user_id, provider), cache_discovery=False)


# ------------------------------------------------------------------ Calendar
def calendar_list_events(user_id: int, start_iso: str, end_iso: str, limit: int = 50) -> list[dict]:
    svc = _service(user_id, "google_calendar", "calendar", "v3")
    tz = config.TIMEZONE
    res = svc.events().list(calendarId="primary", timeMin=f"{start_iso}T00:00:00", timeMax=f"{end_iso}T23:59:59",
                            timeZone=tz, singleEvents=True, orderBy="startTime", maxResults=limit).execute()
    out = []
    for e in res.get("items", []):
        s, en = e.get("start", {}), e.get("end", {})
        sdt, edt = s.get("dateTime", ""), en.get("dateTime", "")
        out.append({"google_event_id": e["id"], "title": e.get("summary", "(no title)"),
                    "date": (sdt or s.get("date", ""))[:10], "start_time": sdt[11:16] or None, "end_time": edt[11:16] or None,
                    "meeting_link": e.get("hangoutLink", ""), "description": e.get("description", ""),
                    "attendees": ",".join(a.get("email", "") for a in e.get("attendees", []))})
    return out


def calendar_create_event(user_id: int, title: str, date: str, start: str, end: str, description: str = "",
                          attendees: list[str] | None = None, with_meet: bool = False) -> dict:
    import uuid

    svc = _service(user_id, "google_calendar", "calendar", "v3")
    body = {"summary": title, "description": description,
            "start": {"dateTime": f"{date}T{start}:00", "timeZone": config.TIMEZONE},
            "end": {"dateTime": f"{date}T{end}:00", "timeZone": config.TIMEZONE}}
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    kwargs = {"calendarId": "primary", "body": body, "sendUpdates": "all" if attendees else "none"}
    if with_meet:
        body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex,
                                                    "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
        kwargs["conferenceDataVersion"] = 1
    ev = svc.events().insert(**kwargs).execute()
    return {"google_event_id": ev["id"], "meeting_link": ev.get("hangoutLink", ""), "html_link": ev.get("htmlLink", "")}


def calendar_delete_event(user_id: int, google_event_id: str) -> None:
    _service(user_id, "google_calendar", "calendar", "v3").events().delete(calendarId="primary", eventId=google_event_id).execute()


# ------------------------------------------------------------------ Gmail
def gmail_read(user_id: int, query: str = "", limit: int = 5) -> list[dict]:
    svc = _service(user_id, "gmail", "gmail", "v1")
    msgs = svc.users().messages().list(userId="me", q=query, maxResults=limit).execute().get("messages", [])
    out = []
    for m in msgs:
        d = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                       metadataHeaders=["Subject", "From", "Date"]).execute()
        h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
        out.append({"id": m["id"], "subject": h.get("Subject", "(No subject)"), "sender": h.get("From", ""),
                    "date": h.get("Date", ""), "snippet": d.get("snippet", ""),
                    "link": f"https://mail.google.com/mail/u/0/#inbox/{m['id']}"})
    return out


def gmail_send(user_id: int, to: str, subject: str, body: str) -> str:
    svc = _service(user_id, "gmail", "gmail", "v1")
    msg = MIMEText(body)
    msg["to"], msg["subject"] = to, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute().get("id", "")
