from __future__ import annotations

from core.llm import LLMError


def ask_llm(ctx, system: str, user: str, role: str = "writer", max_tokens: int = 900) -> str | None:
    """One-shot text generation. Returns None in offline mode or on provider failure (callers fall back)."""
    if not ctx.llm or ctx.llm.is_offline:
        return None
    try:
        return ctx.llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                            temperature=0.4, max_tokens=max_tokens, role=role).strip()
    except LLMError:
        return None


def ask_llm_json(ctx, system: str, user: str, role: str = "writer", max_tokens: int = 1800):
    if not ctx.llm or ctx.llm.is_offline:
        return None
    try:
        return ctx.llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                 role=role, max_tokens=max_tokens)
    except LLMError:
        return None


def fail(msg: str, **extra) -> dict:
    return {"ok": False, "error": msg, **extra}
