"""Research tools: DuckDuckGo web/image/news search and page reading."""
from __future__ import annotations

from integrations import search
from tools.registry import Tool, ToolContext, register

P = lambda t, d, req=False: {"type": t, "description": d, **({"required": True} if req else {})}  # noqa: E731


def _lim(limit) -> int:
    return max(1, min(int(limit or 5), 10))


register(Tool("search_web", "DuckDuckGo web search.", {"query": P("string", "search query", True), "limit": P("integer", "max results")},
              lambda ctx, query, limit=5: search.web(query, _lim(limit)), "research", "read"))
register(Tool("search_news", "DuckDuckGo news search.", {"query": P("string", "search query", True), "limit": P("integer", "max results")},
              lambda ctx, query, limit=5: search.news(query, _lim(limit)), "research", "read"))
register(Tool("search_images", "DuckDuckGo image search.", {"query": P("string", "search query", True), "limit": P("integer", "max results")},
              lambda ctx, query, limit=5: search.images(query, _lim(limit)), "research", "read"))
register(Tool("fetch_page", "Download a web page and return its readable text for deeper reading.", {
    "url": P("string", "http(s) URL", True), "max_chars": P("integer", "default 4000")},
    lambda ctx, url, max_chars=4000: search.fetch_page(url, int(max_chars or 4000)), "research", "read"))
