# Changes from the original "Agenda" app

| Topic | Original | This version |
|---|---|---|
| LLM | OpenAI (paid key) | Free: Groq / Gemini / OpenRouter / Ollama + offline mode, automatic fallbacks |
| Database | PostgreSQL server (Neon) | SQLite, zero setup |
| Agent design | One ReAct agent with ~30 tools and a very long prompt | Supervisor + 7 specialist agents, critic, graph engine |
| Safety | Prompt text asked the model to "confirm first" (not enforced) | Enforced approvals by tool risk level + autonomy modes |
| Scheduling | LLM invented the timetable (could overlap) | Deterministic constraint scheduler + validation |
| Memory | none | Long-term memory (facts, preferences, lessons) |
| Observability | none | Persisted traces, timeline, architecture graph |
| Goals | none | Goal → milestones → tasks, re-planning |
| Email | read/send | + triage, AI drafts, email→task |
| GitHub | tools only | + UI, issue import, AI PR/repo summaries, approvals |
| Calendar | Google only | Local calendar + optional Google sync, Jitsi links |
| Secrets | `client_secret.json` committed | env/secrets only; tokens & keys encrypted |
| Auth | PG `crypt()`, login lost after OAuth redirect | scrypt; session token carried through OAuth redirect |
| Tests | none | 69 automated tests |
