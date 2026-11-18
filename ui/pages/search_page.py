import streamlit as st

from agents import orchestrator
from ui import common as C


def render() -> None:
    st.title("🔍 Web Search & Research")
    st.caption("DuckDuckGo — free, no API key.")
    tab_web, tab_news, tab_img, tab_agent = st.tabs(["Web", "News", "Images", "🤖 Research agent"])
    for tab, tool, label in [(tab_web, "search_web", "web"), (tab_news, "search_news", "news"), (tab_img, "search_images", "images")]:
        with tab:
            q = st.text_input("Query", key=f"q_{label}")
            n = st.slider("Results", 1, 10, 5, key=f"n_{label}")
            if st.button("Search", key=f"go_{label}") and q:
                res = C.run_tool(tool, query=q, limit=n)
                if not res.get("ok"):
                    C.show_result(res)
                    continue
                for r in res["results"]:
                    if label == "images":
                        st.image(r.get("thumbnail") or r.get("image"), caption=r.get("title"))
                    else:
                        st.markdown(f"**[{r['title']}]({r['url']})**  \n{r.get('snippet', '')}")
    with tab_agent:
        st.caption("Runs several searches, reads the best pages and writes a sourced summary (needs a real LLM for best results).")
        topic = st.text_area("Research question", height=80)
        if st.button("🔬 Research this") and topic:
            with st.status("Research agent working…", expanded=True) as status:
                res = orchestrator.run(C.uid(), f"Research and summarise with sources: {topic}", on_event=lambda e: status.markdown(C.format_event(e)))
                status.update(label="Done", state="complete", expanded=False)
            st.markdown(res.answer)
