import streamlit as st

from agents.orchestrator import build_graph
from core import repo
from ui import common as C


def render() -> None:
    uid = C.uid()
    st.title("🔭 Agent Activity")
    tab_runs, tab_arch = st.tabs(["Run traces", "Architecture"])
    with tab_runs:
        runs = repo.list_runs(uid, 40)
        if not runs:
            st.info("No runs yet. Ask the Assistant something.")
            return
        total = sum(r["llm_calls"] for r in runs)
        c = st.columns(3)
        c[0].metric("Runs", len(runs))
        c[1].metric("LLM calls", total)
        c[2].metric("Avg latency", f"{int(sum(r['duration_ms'] for r in runs) / len(runs))} ms")
        labels = {r["id"]: f"#{r['id']} · {r['status']} · {r['query'][:60]}" for r in runs}
        pick = st.selectbox("Run", list(labels), format_func=lambda i: labels[i])
        st.markdown("**Final answer**")
        st.markdown(next(r["final"] for r in runs if r["id"] == pick) or "_(none)_")
        st.markdown("**Timeline**")
        C.render_steps(repo.list_steps(pick))
    with tab_arch:
        st.caption("Supervisor graph (dashed edges are conditional routes). Specialist agents run a bounded Reason → Act → Observe loop over their own tools.")
        st.graphviz_chart(build_graph(None, None, None).to_dot())
        from agents.specialists import SPECIALISTS
        from tools import registry as R

        for s in SPECIALISTS.values():
            with st.expander(f"{s.title} — tools"):
                st.write(", ".join(f"`{t.name}` ({t.risk if isinstance(t.risk, str) else 'dynamic'})" for t in R.tools_for(s.groups + ['memory'])))
