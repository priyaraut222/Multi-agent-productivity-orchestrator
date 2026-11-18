"""Central configuration. Everything is read from environment variables (.env),
Streamlit secrets, or per-user settings stored in the database."""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

APP_NAME = "Multi-Agent Productivity & Goal Orchestration System"
APP_SHORT = "Goal Orchestrator"
APP_ICON = "🧭"
BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str | None = None) -> str | None:
    """Read a setting from the environment, falling back to Streamlit secrets."""
    value = os.getenv(key)
    if value:
        return value.strip()
    try:  # pragma: no cover - only inside Streamlit
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default


DB_PATH = env("DB_PATH", str(BASE_DIR / "data" / "app.db"))
TIMEZONE = env("TIMEZONE", "Asia/Kolkata")
APP_SECRET = env("APP_SECRET", "change-me-in-.env")  # used to encrypt stored tokens/keys
REDIRECT_URI = env("REDIRECT_URL", "http://localhost:8501")

# --- Free LLM providers (all expose an OpenAI-compatible /chat/completions API) ---
PROVIDERS: dict[str, dict] = {
    "groq": {
        "label": "Groq (free tier)",
        "base_url": "https://api.groq.com/openai/v1",
        "model": env("GROQ_MODEL", "openai/gpt-oss-120b"),
        "key_env": "GROQ_API_KEY",
        "needs_key": True,
        "signup": "https://console.groq.com/keys",
    },
    "gemini": {
        "label": "Google Gemini (free tier)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": env("GEMINI_MODEL", "gemini-3.8-flash"),
        "key_env": "GEMINI_API_KEY",
        "needs_key": True,
        "signup": "https://aistudio.google.com/app/apikey",
    },
    "openrouter": {
        "label": "OpenRouter (free models)",
        "base_url": "https://openrouter.ai/api/v1",
        "model": env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "key_env": "OPENROUTER_API_KEY",
        "needs_key": True,
        "signup": "https://openrouter.ai/keys",
    },
    "ollama": {
        "label": "Ollama (local, fully offline)",
        "base_url": env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "model": env("OLLAMA_MODEL", "llama3.1:8b"),
        "key_env": None,
        "needs_key": False,
        "signup": "https://ollama.com/download",
    },
    "offline": {
        "label": "Offline demo mode (no key, limited)",
        "base_url": "",
        "model": "rule-based",
        "key_env": None,
        "needs_key": False,
        "signup": "",
    },
}
DEFAULT_PROVIDER = env("LLM_PROVIDER", "offline")

# --- Integrations (all free tiers) ---
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_CLIENT_SECRETS_FILE = env("GOOGLE_CLIENT_SECRETS_FILE", str(BASE_DIR / "client_secret.json"))
GITHUB_CLIENT_ID = env("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = env("GITHUB_CLIENT_SECRET")
GITHUB_TOKEN = env("GITHUB_TOKEN")  # optional personal access token fallback

# --- Agent runtime limits ---
MAX_WORKER_STEPS = int(env("MAX_WORKER_STEPS", "6"))
MAX_PLAN_STEPS = int(env("MAX_PLAN_STEPS", "4"))
WORK_START = env("WORK_START", "09:00")
WORK_END = env("WORK_END", "18:00")
