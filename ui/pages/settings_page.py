import streamlit as st

from core import config, repo
from core.llm import make_llm
from tools.registry import AUTONOMY_LEVELS
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("⚙️ Settings")
    st.subheader("Language model (free providers)")
    current = repo.get_setting(uid, "llm_provider", config.DEFAULT_PROVIDER)
    names = list(config.PROVIDERS)
    provider = st.selectbox("Provider", names, index=names.index(current) if current in names else names.index("offline"),
                            format_func=lambda n: config.PROVIDERS[n]["label"])
    spec = config.PROVIDERS[provider]
    if spec["signup"]:
        st.markdown(f"Get a free key / install: {spec['signup']}")
    for name, s in config.PROVIDERS.items():
        if s["needs_key"]:
            has = bool(repo.get_setting(uid, f"key_{name}")) or bool(config.env(s["key_env"]))
            key = st.text_input(f"{s['label']} API key {'✅' if has else ''}", type="password", key=f"k_{name}",
                                help="Stored encrypted. Leave empty to keep the existing key. Other keyed providers act as automatic fallbacks.")
            if key:
                repo.set_setting(uid, f"key_{name}", key.strip(), encrypted=True)
    if st.button("Save provider"):
        repo.set_setting(uid, "llm_provider", provider)
        st.success("Saved.")
    if st.button("🧪 Test connection"):
        router = make_llm(uid, provider)
        try:
            out = router.chat([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=20, role="tasks")
            st.success(f"{router.clients[0].provider}: {out[:80]}")
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Autonomy")
    level = repo.get_setting(uid, "autonomy", "ask_external")
    keys = list(AUTONOMY_LEVELS)
    choice = st.radio("How much may agents do without asking?", keys, index=keys.index(level) if level in keys else 1,
                      format_func=lambda k: AUTONOMY_LEVELS[k])
    if choice != level:
        repo.set_setting(uid, "autonomy", choice)
        st.success("Autonomy updated.")

    st.subheader("Working hours")
    c1, c2 = st.columns(2)
    ws = c1.text_input("Start", value=repo.get_setting(uid, "work_start", config.WORK_START))
    we = c2.text_input("End", value=repo.get_setting(uid, "work_end", config.WORK_END))
    if st.button("Save hours"):
        repo.set_setting(uid, "work_start", ws)
        repo.set_setting(uid, "work_end", we)
        st.success("Saved.")
    st.caption(f"Timezone: {config.TIMEZONE} (set TIMEZONE in .env)")
