# Architecture

## 1. Layers
| Layer | Modules | Responsibility |
|---|---|---|
| UI | `app.py`, `ui/` | Streamlit pages; never contain business logic or SQL |
| Agents | `agents/` | Orchestration (graph), worker loops, planning engines |
| Tools | `tools/` | The only way agents touch the world; typed, risk-tagged, approval-gated |
| Integrations | `integrations/` | HTTP/API clients for Google, GitHub, DuckDuckGo |
| Core | `core/` | Config, SQLite + repository, LLM client, scheduler, crypto |

## 2. Supervisor graph (`agents/orchestrator.py`)
```
recall ─▶ supervise ─┬─▶ execute ◀─┐ (loop while plan steps remain)
                     │       └─────┘
                     │       ▼
                     │     critic ─┬─▶ revise ─▶ finalize ─▶ END
                     │             └─────────────▶ finalize
                     └─▶ finalize   (direct answer, e.g. greetings)
```
* **recall** – keyword retrieval from long-term memory (no embeddings → free & offline).
* **supervise** – LLM returns `{"steps":[{"agent","task"}], "direct_answer"}`. Output is validated: unknown agents are dropped,
  malformed JSON triggers one repair retry, then a safe default (`tasks` agent) is used.
* **execute** – runs one worker; later workers receive earlier summaries as context (true multi-agent pipelines, e.g. *research → email → task*).
* **critic** – (1) deterministic grounding checks: a claimed write without evidence, or an undisclosed failure, forces a revision;
  (2) an LLM review comparing draft vs. tool evidence (skipped in *Fast mode*). One revision maximum.
* **finalize** – appends pending approvals to the answer, stores explicit user preferences in memory, persists the trace.

## 3. Worker agents (`agents/base.py`)
Bounded ReAct loop (`MAX_WORKER_STEPS`, default 6). Each turn the model returns **one JSON object**: a tool call or a `final`.
Safeguards: unknown-tool recovery, duplicate-call detection, per-agent tool allow-list, observation truncation,
and a forced wrap-up when the budget is exhausted.

| Agent | Tools (groups) | Notable behaviour |
|---|---|---|
| Task Manager | tasks | priorities from urgency words, time-boxing |
| Calendar | calendar | conflict check → proposes nearest free slot; Meet/Jitsi links |
| Email | email, tasks | draft → approval → send; inbox triage; email→task |
| GitHub | github, tasks | read freely, writes approval-gated; issues→tasks |
| Research | research, tasks | multi-query search, page reading, cited synthesis |
| Goal Planner | goal, tasks | decomposition with validation + fallback template |
| Daily Planner | planner, tasks, calendar | constraint scheduling, overdue recovery, reviews |

## 4. Human-in-the-loop (`tools/registry.py`)
`Tool.risk ∈ {read, write, external}` (can depend on arguments, e.g. a meeting with attendees is *external*).
Autonomy modes: `ask_all` · `ask_external` (default) · `auto`. A gated call is stored in `approvals` with its exact arguments; only the
user can execute it (`run_approved`), and an approval can never be replayed.

## 5. Why a deterministic scheduler?
LLMs miscalculate overlaps and durations. `core/scheduler.py` scores tasks (priority + deadline pressure), places them in free
windows around fixed events and lunch, splits long tasks, adds buffers, and `validate_schedule` proves there are no overlaps.
The LLM only adds the narrative/tips. This is the "LLM advises, algorithm decides" pattern.

## 6. Memory & learning
`memories(kind=fact|preference|habit|lesson)`. Retrieved by keyword overlap and injected into supervisor, workers and planner.
The weekly review stores a one-sentence *lesson* — the system improves its own context over time.

## 7. Observability
`agent_runs` + `agent_steps` store each thought, tool call, observation, critic verdict and revision. The Activity page shows
latency, LLM-call counts and the timeline; the Assistant shows the same trace live while agents work.

## 8. Failure handling matrix
| Failure | Behaviour |
|---|---|
| Provider 429/5xx | retry with back-off → next configured provider |
| All providers down | honest message, no fabricated result |
| Invalid JSON from model | one repair retry → safe fallback |
| Hallucinated tool/args | observation with allowed tools / usage; argument validation & coercion |
| Integration not connected | clear "connect X" error; local features still work |
| Calendar conflict | refuse + suggest free slots |
