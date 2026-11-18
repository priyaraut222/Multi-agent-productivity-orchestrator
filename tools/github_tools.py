"""GitHub tools. Reads are free-flowing; anything that writes to GitHub requires approval."""
from __future__ import annotations

from core import repo
from integrations.github_api import GitHubError, NotConnected, get_client, is_connected
from tools._util import ask_llm, fail
from tools.registry import Tool, ToolContext, register

P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731
GITIGNORES = {"python": "Python", "node": "Node", "java": "Java", "go": "Go", "rust": "Rust", "web": "", "empty": ""}


def _guard(fn):
    def wrapper(ctx: ToolContext, **kw):
        try:
            return fn(ctx, get_client(ctx.user_id), **kw)
        except NotConnected as exc:
            return fail(str(exc))
        except GitHubError as exc:
            return fail(str(exc))
    wrapper.__name__ = fn.__name__
    return wrapper


def github_is_connected(ctx: ToolContext) -> dict:
    ok = is_connected(ctx.user_id)
    return {"connected": ok, "message": "GitHub is connected." if ok else "GitHub is not connected."}


@_guard
def list_repositories(ctx, gh, limit: int = 15):
    rows = gh.repos(int(limit))
    return {"repositories": rows, "count": len(rows), "message": f"{len(rows)} repositories (most recently updated first)."}


@_guard
def get_repository_details(ctx, gh, owner: str, repo: str):
    return {"repository": gh.repo(owner, repo), "message": f"Details for {owner}/{repo}."}


@_guard
def get_repo_structure(ctx, gh, owner: str, repo: str, path: str = ""):
    items = gh.tree(owner, repo, path)
    return {"items": [{"title": f"{'📁' if i['type'] == 'dir' else '📄'} {i['path']}"} for i in items], "tree": items,
            "message": f"{len(items)} entries in /{path}"}


@_guard
def read_file(ctx, gh, owner: str, repo: str, path: str):
    return gh.file(owner, repo, path)


@_guard
def summarize_repository(ctx, gh, owner: str, repo: str):
    info, readme, tree = gh.repo(owner, repo), gh.readme(owner, repo), gh.tree(owner, repo)
    facts = (f"{info['full_name']}: {info.get('description') or 'no description'}. Language {info.get('language')}, "
             f"{info.get('stargazers_count')}★, {info.get('open_issues_count')} open issues. Top-level: "
             + ", ".join(i["name"] for i in tree[:20]))
    text = ask_llm(ctx, "Summarise this GitHub repository for a developer in <=120 words: purpose, tech, how to run, health.",
                   f"{facts}\n\nREADME:\n{readme}", role="writer")
    return {"summary": text or facts, "message": text or facts}


@_guard
def list_issues(ctx, gh, owner: str, repo: str, state: str = "open", limit: int = 15):
    rows = gh.issues(owner, repo, state, int(limit))
    return {"issues": rows, "count": len(rows), "message": f"{len(rows)} {state} issue(s) in {owner}/{repo}."}


@_guard
def create_issue(ctx, gh, owner: str, repo: str, title: str, body: str = "", labels: str = ""):
    r = gh.create_issue(owner, repo, title, body, [x.strip() for x in labels.split(",") if x.strip()])
    return {**r, "message": f"🐙 Created issue #{r['number']}: {r['url']}"}


@_guard
def close_issue(ctx, gh, owner: str, repo: str, issue_number: int):
    r = gh.close_issue(owner, repo, int(issue_number))
    return {**r, "message": f"Closed issue #{issue_number}."}


@_guard
def list_pull_requests(ctx, gh, owner: str, repo: str, state: str = "open", limit: int = 15):
    rows = gh.pulls(owner, repo, state, int(limit))
    return {"pull_requests": rows, "count": len(rows), "message": f"{len(rows)} {state} pull request(s)."}


@_guard
def summarize_pull_request(ctx, gh, owner: str, repo: str, pr_number: int):
    pr = gh.pull(owner, repo, int(pr_number))
    facts = (f"PR #{pr['number']} '{pr['title']}' by {pr['author']}: +{pr['additions']}/-{pr['deletions']} across "
             f"{pr['changed_files']} files. Files: " + ", ".join(f['filename'] for f in pr["files"][:10]))
    text = ask_llm(ctx, "Summarise this pull request for a reviewer in <=120 words: intent, risk areas, what to test.",
                   f"{facts}\n\nDescription:\n{pr['body']}\n\nPatches:\n" + "\n".join(f"{f['filename']}: {f['patch']}" for f in pr["files"][:6]),
                   role="writer")
    return {"summary": text or facts, "pull_request": pr, "message": text or facts}


@_guard
def comment_on_pull_request(ctx, gh, owner: str, repo: str, pr_number: int, comment: str):
    r = gh.comment(owner, repo, int(pr_number), comment)
    return {**r, "message": f"💬 Comment posted: {r['url']}"}


@_guard
def read_notifications(ctx, gh, all_notifications: bool = False):
    rows = gh.notifications(bool(all_notifications))
    return {"notifications": [{"title": f"{n['repo']}: {n['title']}", "id": n["id"], "reason": n["reason"]} for n in rows],
            "count": len(rows), "message": f"{len(rows)} notification(s)."}


@_guard
def mark_notification_as_read(ctx, gh, notification_id: str):
    gh.mark_read(notification_id)
    return {"message": "Marked notification as read."}


@_guard
def create_repository(ctx, gh, name: str, description: str = "", private: bool = False, project_type: str = "empty",
                      license: str = "", files: dict | None = None, enable_pages: bool = False):
    r = gh.create_repo(name, description, bool(private), GITIGNORES.get((project_type or "empty").lower(), ""), license)
    owner = r["full_name"].split("/")[0]
    for path, content in (files or {}).items():
        gh.put_file(owner, name, path, content, f"Add {path}", r["default_branch"])
    pages = gh.enable_pages(owner, name, r["default_branch"]) if enable_pages else ""
    return {**r, "pages_url": pages, "message": f"🐙 Created {r['full_name']}: {r['url']}\nClone: git clone {r['clone']}"
            + (f"\nPages: {pages}" if pages else "")}


@_guard
def issues_to_tasks(ctx, gh, owner: str, repo_name: str = "", repo: str = ""):
    repo_name = repo_name or repo
    rows = gh.issues(owner, repo_name, "open", 30)
    n = 0
    for i in rows:
        if not repo_.search_tasks(ctx.user_id, f"[{owner}/{repo_name}#{i['number']}]", 1):
            repo_.add_task(ctx.user_id, f"[{owner}/{repo_name}#{i['number']}] {i['title']}", description=i["body"], link=i["url"],
                           source="github", priority="high" if "bug" in i["labels"] else "medium", estimated_hours=1.0)
            n += 1
    return {"imported": n, "message": f"Imported {n} new issue(s) from {owner}/{repo_name} as tasks."}


repo_ = repo  # alias: tool parameters named 'repo' shadow the module inside function bodies

register(Tool("github_is_connected", "Check whether GitHub is connected.", {}, github_is_connected, "github", "read"))
register(Tool("list_repositories", "List the user's repositories.", {"limit": P("integer", "max")}, list_repositories, "github", "read"))
_OR = {"owner": P("string", "repo owner/login", True), "repo": P("string", "repo name", True)}
register(Tool("get_repository_details", "Repository metadata.", _OR, get_repository_details, "github", "read"))
register(Tool("get_repo_structure", "List files/folders of a repo path.", {**_OR, "path": P("string", "folder path")}, get_repo_structure, "github", "read"))
register(Tool("read_file", "Read a file from a repo.", {**_OR, "path": P("string", "file path", True)}, read_file, "github", "read"))
register(Tool("summarize_repository", "LLM summary of a repository.", _OR, summarize_repository, "github", "read"))
register(Tool("list_issues", "List issues.", {**_OR, "state": P("string", "open|closed|all"), "limit": P("integer", "max")}, list_issues, "github", "read"))
register(Tool("create_issue", "Open a GitHub issue (requires approval).", {**_OR, "title": P("string", "", True), "body": P("string", ""),
                                                                           "labels": P("string", "comma-separated")},
              create_issue, "github", "external", lambda a: f"Create issue '{a.get('title')}' in {a.get('owner')}/{a.get('repo')}"))
register(Tool("close_issue", "Close an issue (requires approval).", {**_OR, "issue_number": P("integer", "", True)}, close_issue, "github", "external",
              lambda a: f"Close issue #{a.get('issue_number')} in {a.get('owner')}/{a.get('repo')}"))
register(Tool("list_pull_requests", "List pull requests.", {**_OR, "state": P("string", "open|closed|all"), "limit": P("integer", "max")},
              list_pull_requests, "github", "read"))
register(Tool("summarize_pull_request", "LLM review summary of a PR.", {**_OR, "pr_number": P("integer", "", True)},
              summarize_pull_request, "github", "read"))
register(Tool("comment_on_pull_request", "Comment on a PR (requires approval).", {**_OR, "pr_number": P("integer", "", True), "comment": P("string", "", True)},
              comment_on_pull_request, "github", "external", lambda a: f"Comment on PR #{a.get('pr_number')} in {a.get('owner')}/{a.get('repo')}"))
register(Tool("read_notifications", "Read GitHub notifications.", {"all_notifications": P("boolean", "include read")}, read_notifications, "github", "read"))
register(Tool("mark_notification_as_read", "Mark a notification as read.", {"notification_id": P("string", "id", True)},
              mark_notification_as_read, "github", "write"))
register(Tool("create_repository", "Create a repository (optionally with starter files and GitHub Pages). Requires approval.", {
    "name": P("string", "repo name", True), "description": P("string", ""), "private": P("boolean", ""),
    "project_type": P("string", "python|node|java|go|rust|web|empty"), "license": P("string", "e.g. mit"),
    "files": P("object", "map of path -> file content"), "enable_pages": P("boolean", "publish with GitHub Pages")},
    create_repository, "github", "external", lambda a: f"Create GitHub repository '{a.get('name')}'"))
register(Tool("issues_to_tasks", "Import open GitHub issues into the workboard as tasks.", {"owner": P("string", "", True), "repo": P("string", "", True)},
              issues_to_tasks, "github", "write"))
