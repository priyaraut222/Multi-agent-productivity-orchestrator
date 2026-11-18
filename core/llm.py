"""Provider-agnostic LLM client for FREE endpoints (Groq, Gemini, OpenRouter, Ollama) + offline fallback.

All providers speak the OpenAI-compatible ``/chat/completions`` protocol, so a single small
``requests`` client is enough - no paid SDK, no vendor lock-in.  Agents use a plain-JSON action
protocol (see ``agents/base.py``) instead of native function calling, because free/small models
implement native tool calling inconsistently.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import requests

from core import config, repo


class LLMError(RuntimeError):
    pass


def extract_json(text: str):
    """Pull the first JSON object/array out of an LLM reply (handles ``` fences and chatter)."""
    if text is None:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(t)):
                ch = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(t[start:i + 1])
                        except Exception:
                            break
            start = t.find(opener, start + 1)
    return None


@dataclass
class LLMClient:
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    timeout: int = 60
    calls: int = 0
    last_error: str = ""

    def __post_init__(self):
        spec = config.PROVIDERS[self.provider]
        self.model = self.model or spec["model"]
        self.base_url = self.base_url or spec["base_url"]

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1500, role: str = "") -> str:
        if self.provider == "offline":
            from core.offline_llm import offline_chat

            self.calls += 1
            return offline_chat(messages, role)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        delay = 1.5
        for attempt in range(3):
            try:
                resp = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload,
                                     timeout=self.timeout)
            except requests.RequestException as exc:
                self.last_error = str(exc)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 200:
                self.calls += 1
                try:
                    return resp.json()["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, ValueError) as exc:
                    raise LLMError(f"Malformed response from {self.provider}: {exc}")
            if resp.status_code in (429, 500, 502, 503, 504):
                self.last_error = f"{resp.status_code}: {resp.text[:160]}"
                wait = float(resp.headers.get("retry-after", delay)) if str(resp.headers.get("retry-after", "")).replace(".", "").isdigit() else delay
                time.sleep(min(wait, 8))
                delay *= 2
                continue
            raise LLMError(f"{self.provider} error {resp.status_code}: {resp.text[:200]}")
        raise LLMError(f"{self.provider} unavailable after retries ({self.last_error})")


@dataclass
class LLMRouter:
    """Tries the primary provider first, then any other configured free provider (rate-limit resilience)."""

    clients: list[LLMClient] = field(default_factory=list)
    calls: int = 0
    used: str = ""

    @property
    def is_offline(self) -> bool:
        return bool(self.clients) and self.clients[0].provider == "offline"

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1500, role: str = "") -> str:
        errors = []
        for client in self.clients:
            try:
                out = client.chat(messages, temperature, max_tokens, role)
                self.calls += 1
                self.used = client.provider
                return out
            except LLMError as exc:
                errors.append(str(exc))
        raise LLMError("All LLM providers failed: " + " | ".join(errors))

    def chat_json(self, messages: list[dict], role: str = "", temperature: float = 0.2, max_tokens: int = 1500,
                  retries: int = 1):
        """Ask for JSON; if parsing fails, ask the model once to repair its own output."""
        msgs = list(messages)
        for attempt in range(retries + 1):
            raw = self.chat(msgs, temperature=temperature, max_tokens=max_tokens, role=role)
            data = extract_json(raw)
            if data is not None:
                return data
            msgs = msgs + [{"role": "assistant", "content": raw},
                           {"role": "user", "content": "Your reply was not valid JSON. Reply again with ONLY the JSON object."}]
        return None


def available_providers(user_id: int | None = None) -> dict[str, str]:
    """provider -> api key (empty string for keyless providers) for providers usable right now."""
    out = {}
    for name, spec in config.PROVIDERS.items():
        if name == "offline":
            continue
        if not spec["needs_key"]:
            continue  # ollama is only used if explicitly selected (may not be running)
        key = (repo.get_setting(user_id, f"key_{name}") if user_id else None) or (
            config.env(spec["key_env"]) if spec["key_env"] else None)
        if key:
            out[name] = key
    return out


def make_llm(user_id: int | None = None, provider: str | None = None) -> LLMRouter:
    """Build the router for a user: selected provider first, other keyed providers as fallbacks."""
    selected = provider or (repo.get_setting(user_id, "llm_provider") if user_id else None) or config.DEFAULT_PROVIDER
    if selected not in config.PROVIDERS:
        selected = "offline"
    keys = available_providers(user_id)
    clients: list[LLMClient] = []
    if selected == "offline":
        return LLMRouter([LLMClient("offline")])
    if selected == "ollama":
        clients.append(LLMClient("ollama"))
    elif selected in keys:
        clients.append(LLMClient(selected, api_key=keys[selected]))
    for name, key in keys.items():
        if name != selected:
            clients.append(LLMClient(name, api_key=key))
    if not clients:  # nothing configured -> graceful offline mode
        clients.append(LLMClient("offline"))
    return LLMRouter(clients)
