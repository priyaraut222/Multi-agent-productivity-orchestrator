"""GitHub REST client (free). Works with OAuth tokens or a personal access token."""
from __future__ import annotations

import base64

import requests

from core import config, repo

API = "https://api.github.com"
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
SCOPES = "repo user notifications read:org"


class GitHubError(RuntimeError):
    pass


class NotConnected(GitHubError):
    pass


def oauth_configured() -> bool:
    return bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET)


def auth_url(session_token: str) -> str:
    return (f"{AUTHORIZE_URL}?client_id={config.GITHUB_CLIENT_ID}&redirect_uri={config.REDIRECT_URI}"
            f"&scope={SCOPES.replace(' ', '%20')}&state=github.{session_token}")


def exchange_code(code: str) -> str:
    r = requests.post(TOKEN_URL, data={"client_id": config.GITHUB_CLIENT_ID, "client_secret": config.GITHUB_CLIENT_SECRET,
                                       "code": code, "redirect_uri": config.REDIRECT_URI},
                      headers={"Accept": "application/json"}, timeout=20)
    data = r.json() if r.ok else {}
    if "access_token" not in data:
        raise GitHubError(data.get("error_description", "GitHub did not return a token"))
    return data["access_token"]


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"}

    def _req(self, method: str, path: str, **kw):
        try:
            r = requests.request(method, f"{API}{path}", headers=self.h, timeout=25, **kw)
        except requests.RequestException as exc:
            raise GitHubError(f"Network error: {exc}")
        if r.status_code == 204:
            return None
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text[:150])
            except ValueError:
                msg = r.text[:150]
            raise GitHubError(f"GitHub {r.status_code}: {msg}")
        return r.json()

    # --- account & repos
    def user(self):
        return self._req("GET", "/user")

    def repos(self, limit: int = 20):
        rows = self._req("GET", "/user/repos", params={"sort": "updated", "per_page": min(limit, 100)})
        return [{"full_name": r["full_name"], "name": r["name"], "owner": r["owner"]["login"], "private": r["private"],
                 "description": r.get("description") or "", "language": r.get("language"), "stars": r["stargazers_count"],
                 "open_issues": r["open_issues_count"], "updated": r["updated_at"], "url": r["html_url"]} for r in rows]

    def repo(self, owner: str, name: str):
        r = self._req("GET", f"/repos/{owner}/{name}")
        return {k: r.get(k) for k in ("full_name", "description", "language", "stargazers_count", "forks_count",
                                      "open_issues_count", "default_branch", "html_url", "pushed_at", "topics", "license")}

    def tree(self, owner: str, name: str, path: str = ""):
        rows = self._req("GET", f"/repos/{owner}/{name}/contents/{path}")
        rows = rows if isinstance(rows, list) else [rows]
        return [{"name": r["name"], "type": r["type"], "path": r["path"], "size": r.get("size", 0)} for r in rows]

    def file(self, owner: str, name: str, path: str, max_chars: int = 6000):
        r = self._req("GET", f"/repos/{owner}/{name}/contents/{path}")
        if isinstance(r, list):
            raise GitHubError(f"'{path}' is a directory")
        text = base64.b64decode(r.get("content", "")).decode("utf-8", errors="replace")
        return {"path": path, "content": text[:max_chars], "truncated": len(text) > max_chars}

    def readme(self, owner: str, name: str, max_chars: int = 4000):
        try:
            r = self._req("GET", f"/repos/{owner}/{name}/readme")
            return base64.b64decode(r.get("content", "")).decode("utf-8", errors="replace")[:max_chars]
        except GitHubError:
            return ""

    # --- issues & PRs
    def issues(self, owner: str, name: str, state: str = "open", limit: int = 20):
        rows = self._req("GET", f"/repos/{owner}/{name}/issues", params={"state": state, "per_page": min(limit, 100)})
        return [{"number": i["number"], "title": i["title"], "state": i["state"], "author": i["user"]["login"],
                 "labels": [lb["name"] for lb in i.get("labels", [])], "url": i["html_url"], "body": (i.get("body") or "")[:300]}
                for i in rows if "pull_request" not in i]

    def create_issue(self, owner: str, name: str, title: str, body: str = "", labels: list[str] | None = None):
        r = self._req("POST", f"/repos/{owner}/{name}/issues", json={"title": title, "body": body, "labels": labels or []})
        return {"number": r["number"], "url": r["html_url"]}

    def close_issue(self, owner: str, name: str, number: int):
        r = self._req("PATCH", f"/repos/{owner}/{name}/issues/{number}", json={"state": "closed"})
        return {"number": r["number"], "state": r["state"], "url": r["html_url"]}

    def pulls(self, owner: str, name: str, state: str = "open", limit: int = 20):
        rows = self._req("GET", f"/repos/{owner}/{name}/pulls", params={"state": state, "per_page": min(limit, 100)})
        return [{"number": p["number"], "title": p["title"], "author": p["user"]["login"], "state": p["state"],
                 "draft": p.get("draft", False), "url": p["html_url"]} for p in rows]

    def pull(self, owner: str, name: str, number: int):
        p = self._req("GET", f"/repos/{owner}/{name}/pulls/{number}")
        files = self._req("GET", f"/repos/{owner}/{name}/pulls/{number}/files", params={"per_page": 30})
        return {"number": number, "title": p["title"], "body": (p.get("body") or "")[:1500], "author": p["user"]["login"],
                "additions": p["additions"], "deletions": p["deletions"], "changed_files": p["changed_files"],
                "mergeable": p.get("mergeable"), "url": p["html_url"],
                "files": [{"filename": f["filename"], "status": f["status"], "changes": f["changes"],
                           "patch": (f.get("patch") or "")[:500]} for f in files[:15]]}

    def comment(self, owner: str, name: str, number: int, body: str):
        r = self._req("POST", f"/repos/{owner}/{name}/issues/{number}/comments", json={"body": body})
        return {"url": r["html_url"]}

    # --- notifications
    def notifications(self, all_: bool = False, limit: int = 20):
        rows = self._req("GET", "/notifications", params={"all": str(all_).lower(), "per_page": limit})
        return [{"id": n["id"], "title": n["subject"]["title"], "type": n["subject"]["type"],
                 "repo": n["repository"]["full_name"], "reason": n["reason"], "unread": n["unread"]} for n in rows]

    def mark_read(self, thread_id: str):
        self._req("PATCH", f"/notifications/threads/{thread_id}")

    # --- creation
    def create_repo(self, name: str, description: str = "", private: bool = False, gitignore: str = "", license_: str = ""):
        body = {"name": name, "description": description, "private": private, "auto_init": True}
        if gitignore:
            body["gitignore_template"] = gitignore
        if license_:
            body["license_template"] = license_
        r = self._req("POST", "/user/repos", json=body)
        return {"full_name": r["full_name"], "url": r["html_url"], "clone": r["clone_url"], "default_branch": r["default_branch"]}

    def put_file(self, owner: str, name: str, path: str, content: str, message: str, branch: str = "main"):
        sha = None
        try:
            existing = self._req("GET", f"/repos/{owner}/{name}/contents/{path}", params={"ref": branch})
            sha = existing.get("sha")
        except GitHubError:
            pass
        body = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
        if sha:
            body["sha"] = sha
        self._req("PUT", f"/repos/{owner}/{name}/contents/{path}", json=body)

    def enable_pages(self, owner: str, name: str, branch: str = "main"):
        try:
            self._req("POST", f"/repos/{owner}/{name}/pages", json={"source": {"branch": branch, "path": "/"}})
        except GitHubError as exc:
            if "409" not in str(exc):  # 409 = already enabled
                raise
        return f"https://{owner}.github.io/{name}/"


def get_client(user_id: int) -> GitHubClient:
    data = repo.get_token(user_id, "github")
    token = (data or {}).get("access_token") or config.GITHUB_TOKEN
    if not token:
        raise NotConnected("GitHub is not connected. Add a token or connect via OAuth on the Authorization page.")
    return GitHubClient(token)


def is_connected(user_id: int) -> bool:
    return bool((repo.get_token(user_id, "github") or {}).get("access_token") or config.GITHUB_TOKEN)
