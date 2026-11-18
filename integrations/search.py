"""DuckDuckGo search (free, no API key) + lightweight page fetching for research."""
from __future__ import annotations

import re

import requests

try:
    from ddgs import DDGS

    DDGS_AVAILABLE = True
except ImportError:  # pragma: no cover
    try:
        from duckduckgo_search import DDGS  # legacy package name

        DDGS_AVAILABLE = True
    except ImportError:
        DDGS = None
        DDGS_AVAILABLE = False


def _run(kind: str, query: str, limit: int) -> dict:
    if not DDGS_AVAILABLE:
        return {"ok": False, "error": "Search library not installed. Run: pip install ddgs"}
    try:
        with DDGS() as ddgs:
            fn = {"web": ddgs.text, "images": ddgs.images, "news": ddgs.news}[kind]
            rows = list(fn(query, max_results=limit))
    except Exception as exc:
        return {"ok": False, "error": f"{kind} search failed: {exc}"}
    return {"ok": True, "rows": rows}


def web(query: str, limit: int = 5) -> dict:
    r = _run("web", query, limit)
    if not r["ok"]:
        return r
    results = [{"title": x.get("title"), "url": x.get("href") or x.get("url"), "snippet": (x.get("body") or "")[:300]}
               for x in r["rows"]]
    return {"ok": True, "results": results, "count": len(results), "message": f"Found {len(results)} web results for '{query}'."}


def images(query: str, limit: int = 5) -> dict:
    r = _run("images", query, limit)
    if not r["ok"]:
        return r
    results = [{"title": x.get("title"), "image": x.get("image"), "thumbnail": x.get("thumbnail"), "url": x.get("url"),
                "source": x.get("source")} for x in r["rows"]]
    return {"ok": True, "results": results, "count": len(results), "message": f"Found {len(results)} images for '{query}'."}


def news(query: str, limit: int = 5) -> dict:
    r = _run("news", query, limit)
    if not r["ok"]:
        return r
    results = [{"title": x.get("title"), "url": x.get("url"), "source": x.get("source"), "date": x.get("date"),
                "snippet": (x.get("body") or "")[:300]} for x in r["rows"]]
    return {"ok": True, "results": results, "count": len(results), "message": f"Found {len(results)} news items for '{query}'."}


def fetch_page(url: str, max_chars: int = 4000) -> dict:
    """Download a page and return readable text (scripts/styles stripped)."""
    if not re.match(r"^https?://", url or ""):
        return {"ok": False, "error": "URL must start with http:// or https://"}
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (research-agent)"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Could not fetch page: {exc}"}
    html = resp.text
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"ok": True, "url": url, "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
            "text": text[:max_chars], "truncated": len(text) > max_chars}
