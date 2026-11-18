"""Test helpers: temp database, scripted LLM, and a fake `streamlit` module for UI smoke tests."""
from __future__ import annotations

import os
import sys
import tempfile
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db, repo  # noqa: E402
from core.llm import LLMRouter  # noqa: E402


def fresh_db() -> int:
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.reset_for_tests(path)
    return repo.create_user("alice", "password123", "alice@example.com", "Alice")


class ScriptedRouter(LLMRouter):
    """Plays back canned replies per role, so the real agent loop runs without any network."""

    def __init__(self, script: dict[str, list[str]]):
        super().__init__(clients=[])
        self.script = {k: list(v) for k, v in script.items()}
        self.log: list[tuple[str, str]] = []

    @property
    def is_offline(self) -> bool:
        return False

    def chat(self, messages, temperature=0.3, max_tokens=1500, role=""):
        self.calls += 1
        self.log.append((role, messages[-1]["content"][:200]))
        queue = self.script.get(role)
        if not queue:
            raise AssertionError(f"unexpected LLM call for role '{role}'; last msg: {messages[-1]['content'][:120]}")
        return queue.pop(0)


class _State(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class _Ctx:
    """Context manager / column object: widgets called on it behave like the top-level st.* widgets."""

    fake = None
    WIDGETS = {"button", "form_submit_button", "toggle", "checkbox", "text_input", "text_area", "number_input", "slider",
               "date_input", "time_input", "selectbox", "radio", "columns", "tabs", "container", "expander", "status", "spinner",
               "chat_message", "form", "chat_input"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self.WIDGETS:
            return getattr(_Ctx.fake, name)
        return MagicMock(name=f"ctx.{name}")


class FakeStreamlit(types.ModuleType):
    """Just enough of the Streamlit API for pages to execute end-to-end in tests."""

    def __init__(self):
        super().__init__("streamlit")
        self.session_state = _State()
        self.query_params = {}
        self.pressed: set[str] = set()
        self.sidebar = _Ctx()
        self.secrets = {}
        _Ctx.fake = self

    def _ctx(self, *a, **k):
        return _Ctx()

    container = expander = form = status = spinner = chat_message = _ctx

    def cache_resource(self, *a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

    def set_page_config(self, *a, **k):
        pass

    def _pressed(self, label, key):
        return label in self.pressed or (key is not None and key in self.pressed)

    def button(self, label, key=None, **k):
        return self._pressed(label, key)

    form_submit_button = button

    def toggle(self, label, value=False, **k):
        return value

    checkbox = toggle

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Ctx() for _ in range(n)]

    def tabs(self, labels):
        return [_Ctx() for _ in labels]

    def _keyed(self, key, value):
        if key:
            self.session_state.setdefault(key, value)
            return self.session_state[key]
        return value

    def text_input(self, label, value="", key=None, **k):
        return self._keyed(key, value)

    text_area = text_input

    def number_input(self, label, min_value=0, max_value=100, value=1, step=1, **k):
        return value

    def slider(self, label, min_value=0, max_value=100, value=None, **k):
        return value if value is not None else min_value

    def date_input(self, label, value=None, **k):
        return value

    def time_input(self, label, value=None, **k):
        return value

    def selectbox(self, label, options, index=0, key=None, **k):
        opts = list(options)
        return self._keyed(key, opts[index] if opts else None)

    radio = selectbox

    def chat_input(self, *a, **k):
        return self.session_state.get("_chat_prompt")

    def rerun(self):
        pass

    def stop(self):
        pass

    def __getattr__(self, name):  # any other st.* call (markdown, write, metric, ...) is a no-op
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name=f"st.{name}")


def install_fake_streamlit() -> FakeStreamlit:
    fake = FakeStreamlit()
    sys.modules["streamlit"] = fake
    return fake
