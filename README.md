# 🧭 Multi-Agent Productivity & Goal Orchestration System

A team of specialised AI agents that **plan goals, schedule time, triage email, track GitHub work and research the web** —
while a human stays in control of every external action. Built with Streamlit and a **100 % free stack**
(free LLM tiers, SQLite, free Google/GitHub APIs, DuckDuckGo). No OpenAI key. No paid service. No database server.

> Evolved from an earlier single-agent "chatbot with tools" app. The focus of this version is the **agentic architecture**:
> supervisor routing, specialist agents, a critic, human-in-the-loop approvals, long-term memory and full run tracing.

## ✨ Features (all original features kept, plus new agentic ones)

| Area | What you get |
|---|---|
| 📊 **Dashboard** | Live metrics, rule-based insights, AI coach recommendations, 14-day completion chart, goals & today's agenda |
| 🤖 **Assistant** | One chat box → Supervisor routes to specialist agents; live "agents at work" trace; inline approval buttons |
| 📅 **Calendar** | Local calendar (works offline) + optional two-way Google Calendar sync, conflict detection, free-slot search, free video links (Google Meet or Jitsi) |
| 📧 **Gmail** | Read/search, **AI inbox triage**, AI-drafted emails, send (approval-gated), email → task |
| 🐙 **GitHub** | Repos, issues, PRs, notifications, AI repo/PR summaries, create repo (+Pages), import issues as tasks — writes are approval-gated |
| 🔍 **Search & Research** | DuckDuckGo web/image/news + a multi-step **Research agent** that reads pages and cites sources |
| 🗓️ **Today's Plan** | Constraint scheduler (never overlaps, verified) + LLM coaching narrative; one-click apply |
| 🧠 **Workboard** | Kanban (to-do / in-progress / blocked / done), assignees, goal & due filters, meetings list |
| 🎯 **Goals** *(new)* | Goal → milestones → tasks decomposition with preview-before-save and adaptive re-planning |
| ✅ **Approvals** *(new)* | Human-in-the-loop queue for emails, invites, GitHub writes — with exact arguments shown |
| 🧠 **Agent Memory** *(new)* | Long-term preferences/facts/lessons injected into every agent; fully user-editable |
| 🔭 **Agent Activity** *(new)* | Persisted trace of every thought, tool call and observation; architecture graph; latency & LLM-call stats |
| 👥 **Collaborators** | Requests, team list, assign tasks, invite to meetings |
| 🔌 **Connections / ⚙️ Settings** | OAuth + token connect, encrypted API keys, provider choice, autonomy level, working hours |

## 🏗️ Architecture

```
                         ┌─────────────────────────── Supervisor graph ───────────────────────────┐
 user ─▶ recall memory ─▶│ supervise (route)  ──▶ execute worker (loop over plan steps)           │
                         │        │ direct answer        │                                         │
                         │        ▼                      ▼                                         │
                         │    finalize ◀── revise ◀── critic (grounding check + LLM review)        │
                         └───────────────────────────────────────────────────────────────────────┘
 Workers (bounded Reason→Act→Observe loops, each with its own restricted toolset):
   Task Manager · Calendar · Email · GitHub · Research · Goal Planner · Daily Planner
 Tool registry:  typed args · risk level (read / write / external) · approval gating · audit trail
```

Key design decisions (see `docs/ARCHITECTURE.md` for detail):

1. **Custom state-graph engine** (`agents/graph.py`, ~100 lines, LangGraph-style: nodes, conditional edges, cycles, recursion limit,
   DOT export). Zero dependency, fully unit-tested, and easy to explain.
2. **Plain-JSON action protocol** instead of native function calling — free/small models implement tool calling inconsistently,
   JSON + a repair retry works on all of them (Groq, Gemini, OpenRouter, Ollama).
3. **LLMs advise, algorithms decide.** Time placement is done by a deterministic scheduler (`core/scheduler.py`) and validated;
   the LLM only ranks, explains and coaches. Overlaps are impossible by construction.
4. **Human-in-the-loop by risk level.** `read` tools run freely, `write` tools change local data, `external` tools (send email,
   invite attendees, touch GitHub) are queued until you approve. Three autonomy modes in Settings.
5. **Grounded answers.** A critic compares the draft with tool evidence; false "I sent it" claims and hidden failures trigger a revision.
6. **Resilience.** Provider fallback chain (rate-limited on Groq → Gemini → OpenRouter), retries with back-off, step budgets,
   duplicate-call guard, graceful degradation to Offline demo mode.
7. **Observability.** Every run is stored (`agent_runs`, `agent_steps`) and rendered as a timeline.

## 🚀 Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit (see below)
python scripts/seed_demo.py                            # optional: demo / demo12345 with sample data
streamlit run app.py
```

Python 3.10+ is required. **No database server**: SQLite is created automatically in `data/app.db`.

### 1. Free LLM (pick one — takes 2 minutes)
| Provider | Free? | Setup |
|---|---|---|
| **Groq** (recommended: fast) | free tier | key at <https://console.groq.com/keys> → `GROQ_API_KEY` |
| **Google Gemini** | free tier | key at <https://aistudio.google.com/app/apikey> → `GEMINI_API_KEY` |
| **OpenRouter** | free models | key at <https://openrouter.ai/keys> → `OPENROUTER_API_KEY` |
| **Ollama** | fully local | install from <https://ollama.com>, `ollama pull llama3.1:8b`, set `LLM_PROVIDER=ollama` |
| **Offline demo** | no key | rule-based, limited — good for a first look and for tests |

You can also paste keys in **Settings** (stored encrypted). Free-tier model names change over time; override with
`GROQ_MODEL`, `GEMINI_MODEL`, … if one is retired. Providers with a key are used automatically as fallbacks.

### 2. Google Calendar & Gmail (optional, free)
1. Google Cloud Console → create a project → enable **Google Calendar API** and **Gmail API**.
2. OAuth consent screen → add yourself as a test user.
3. Credentials → *OAuth client ID* → type **Web application** → authorised redirect URI `http://localhost:8501`.
4. Put the id/secret in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) → **Connections** → Connect.

Without this, the built-in local calendar and Jitsi meeting links work out of the box.

### 3. GitHub (optional, free)
**Connections → "Use a personal access token"** (scopes `repo`, `notifications`) — or configure an OAuth app via `GITHUB_CLIENT_ID/SECRET`.

## 🎬 Demo script (5 minutes)
Try these in **Assistant** (see `docs/DEMO.md` for what to point out):
1. `Plan my day` → then open **Today's Plan** and apply it.
2. `Schedule a design review tomorrow 3pm with bob@example.com about the launch` → lands in **Approvals** (external invite).
3. `Add task finish report tomorrow 3pm urgent for 2 hours`, then `Schedule a meeting tomorrow 3:30pm-4:30pm about sync` → conflict detected, free slots proposed.
4. `I want to learn machine learning by Jan 14` → milestones + tasks; see progress in **Goals**.
5. `Remember that I prefer deep work in the morning` → **Memory** page; re-run "Plan my day".
6. Open **Agent Activity** to show the trace of any run and the architecture graph.

## 🧪 Tests
```bash
python -m unittest discover -s tests -v      # or: pytest
```
69 tests: scheduler correctness, repository isolation, LLM retry/fallback/JSON repair, graph engine, the full supervisor loop with a
scripted LLM (multi-step plans, critic revision, hallucinated tools, duplicate calls, provider outage, autonomy modes), approval
lifecycle, GitHub/Gmail/Calendar tools with mocked services, OAuth session restore, and a smoke test that executes **every Streamlit
page** against a fake Streamlit module.

## 📁 Project structure
```
app.py                   Streamlit entry: auth, navigation, OAuth callback
core/                    config · sqlite db · repo (all SQL) · llm (free providers + router) · offline_llm
                         scheduler (constraint planner) · timeparse · crypto · security
agents/                  graph (engine) · orchestrator (supervisor graph) · base (ReAct worker) · specialists
                         planner · goals · insights · tracing
tools/                   registry (risk/approval gating) · task · calendar · email · github · research · planning · memory
integrations/            google (OAuth, Calendar, Gmail) · github_api · search (DuckDuckGo)
ui/                      common helpers + pages/ (one module per page)
scripts/                 seed_demo.py · gen_tools_doc.py
tests/                   unit, agent-loop, tool and UI smoke tests
docs/                    ARCHITECTURE.md · DEMO.md · CHANGES_FROM_ORIGINAL.md
TOOLS.md                 generated tool catalogue (agent → tools → risk)
```

## 🔒 Security notes
- Passwords hashed with scrypt; API keys and OAuth tokens encrypted at rest (Fernet, key derived from `APP_SECRET` — **set your own**).
- Never commit `.env` or `client_secret.json` (both are in `.gitignore`).
- OAuth logins survive the redirect via a server-side session token carried in the `state` parameter.
- Agents cannot perform external actions without approval in the default mode; every action is logged.

## ⚠️ Known limitations (honest)
- Quality depends on the free model you choose; very small local models may need `MAX_WORKER_STEPS` raised.
- Offline demo mode is rule-based and understands only simple phrasing.
- Free tiers are rate limited; the app retries and falls back, but heavy use may still pause briefly.
- Google OAuth apps in "testing" status expire refresh tokens after 7 days (Google policy) — simply reconnect.
- Single-user-per-session design; deploy behind HTTPS if exposed publicly.

## 🙏 Acknowledgement
Rebuilt from the open-source "Agenda" project (MIT licence, see `LICENSE`).
