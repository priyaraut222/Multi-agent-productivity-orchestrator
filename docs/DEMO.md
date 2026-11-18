# Demo guide (for evaluators)

| Prompt / action | What to point out |
|---|---|
| `Plan my day` | Planner agent; overlap-free schedule validated by code; narrative from the LLM |
| `Schedule a design review tomorrow 3pm with bob@example.com about the launch` | Meeting + attendees is *external* → queued in **Approvals**; nothing happens until approved |
| `Schedule a meeting tomorrow 3:30pm` (twice) | Conflict detection and free-slot suggestions instead of double-booking |
| `Research the pros and cons of SQLite vs Postgres for small apps, then create a task to decide` | Multi-agent pipeline (research → tasks) with cited sources |
| `I want to learn machine learning by Jan 14` | Goal decomposition; preview/save flow in **Goals**; progress bars |
| `Triage my unread emails and turn action items into tasks` | Email agent classification → task creation (needs Gmail connected) |
| `Remember that I prefer deep work in the morning` → `Plan my day` | Long-term memory influencing the planner |
| **Agent Activity** | Full trace (thought → tool → observation → critic) and the architecture graph |
| **Settings → Autonomy** | Switch between ask-everything / ask-external / autonomous |
