# Tool catalogue

Generated from the tool registry. Risk levels drive the human-in-the-loop policy:
🟢 read = always allowed · 🟡 write = changes local data · 🔴 external = affects other people/services, queued for approval.

## Task Manager agent

You manage the user's workboard: to-dos, tasks, priorities, deadlines and assignments.

| Tool | Risk | Purpose |
|---|---|---|
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |

## Calendar agent

You manage meetings and time blocks, check conflicts and find free slots.

| Tool | Risk | Purpose |
|---|---|---|
| `get_calendar_events(start_date: string, end_date: string)` | 🟢 read | List calendar events in a date range (syncs Google Calendar if connected). |
| `check_schedule_conflicts(date*: string, start_time*: string, end_time*: string)` | 🟢 read | Check whether a time range collides with existing events. |
| `find_free_slots(date: string, duration_hours: number, work_start: string, work_end: string)` | 🟢 read | Find free windows on a day. |
| `schedule_meeting(title*: string, date*: string, start_time*: string, end_time: string, duration_hours: number, attendees: string, description: string, with_meet: boolean, allow_conflict: boolean)` | write / external (depends on arguments) | Create a meeting with an automatic video link (Google Meet if connected, else Jitsi). Refuses on conflicts and suggests free slots. |
| `add_task_to_calendar(task_id*: integer, date: string, start_time: string, end_time: string)` | 🟡 write | Time-block an existing task on the calendar. |
| `reschedule_event(event_id*: integer, date: string, start_time: string, end_time: string)` | 🟡 write | Move an event. |
| `delete_event(event_id*: integer)` | 🟡 write | Delete an event. |
| `generate_meeting_link(event_id*: integer)` | 🟡 write | Attach a video-meeting link to an event. |
| `get_collaborators(search: string)` | 🟢 read | Search the user's collaborators. |
| `add_collaborators_to_event(event_id*: integer, collaborators*: string)` | 🟡 write | Add collaborators as attendees of an event. |
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |

## Email agent

You read, triage, draft and send email through Gmail.

| Tool | Risk | Purpose |
|---|---|---|
| `read_emails(query: string, limit: integer)` | 🟢 read | Read/search Gmail (supports from:, subject:, is:unread). |
| `send_email(to*: string, subject*: string, body*: string)` | 🔴 external (approval) | Send an email via Gmail (requires human approval). |
| `draft_email(to*: string, intent*: string, tone: string, context: string)` | 🟢 read | Compose an email draft with the LLM WITHOUT sending it. |
| `triage_inbox(query: string, limit: integer)` | 🟢 read | Classify recent emails into urgent/action/meeting/fyi/ignore. |
| `email_to_task(subject*: string, sender: string, snippet: string, priority: string, due_date: string)` | 🟡 write | Turn an email into a workboard task. |
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |

## GitHub agent

You work with the user's GitHub repositories, issues, pull requests and notifications.

| Tool | Risk | Purpose |
|---|---|---|
| `github_is_connected()` | 🟢 read | Check whether GitHub is connected. |
| `list_repositories(limit: integer)` | 🟢 read | List the user's repositories. |
| `get_repository_details(owner*: string, repo*: string)` | 🟢 read | Repository metadata. |
| `get_repo_structure(owner*: string, repo*: string, path: string)` | 🟢 read | List files/folders of a repo path. |
| `read_file(owner*: string, repo*: string, path*: string)` | 🟢 read | Read a file from a repo. |
| `summarize_repository(owner*: string, repo*: string)` | 🟢 read | LLM summary of a repository. |
| `list_issues(owner*: string, repo*: string, state: string, limit: integer)` | 🟢 read | List issues. |
| `create_issue(owner*: string, repo*: string, title*: string, body: string, labels: string)` | 🔴 external (approval) | Open a GitHub issue (requires approval). |
| `close_issue(owner*: string, repo*: string, issue_number*: integer)` | 🔴 external (approval) | Close an issue (requires approval). |
| `list_pull_requests(owner*: string, repo*: string, state: string, limit: integer)` | 🟢 read | List pull requests. |
| `summarize_pull_request(owner*: string, repo*: string, pr_number*: integer)` | 🟢 read | LLM review summary of a PR. |
| `comment_on_pull_request(owner*: string, repo*: string, pr_number*: integer, comment*: string)` | 🔴 external (approval) | Comment on a PR (requires approval). |
| `read_notifications(all_notifications: boolean)` | 🟢 read | Read GitHub notifications. |
| `mark_notification_as_read(notification_id*: string)` | 🟡 write | Mark a notification as read. |
| `create_repository(name*: string, description: string, private: boolean, project_type: string, license: string, files: object, enable_pages: boolean)` | 🔴 external (approval) | Create a repository (optionally with starter files and GitHub Pages). Requires approval. |
| `issues_to_tasks(owner*: string, repo*: string)` | 🟡 write | Import open GitHub issues into the workboard as tasks. |
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |

## Research agent

You research topics on the web with DuckDuckGo and produce sourced, concise answers.

| Tool | Risk | Purpose |
|---|---|---|
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `search_web(query*: string, limit: integer)` | 🟢 read | DuckDuckGo web search. |
| `search_news(query*: string, limit: integer)` | 🟢 read | DuckDuckGo news search. |
| `search_images(query*: string, limit: integer)` | 🟢 read | DuckDuckGo image search. |
| `fetch_page(url*: string, max_chars: integer)` | 🟢 read | Download a web page and return its readable text for deeper reading. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |

## Goal Planner agent

You turn ambitious goals into milestones and scheduled tasks, and track progress.

| Tool | Risk | Purpose |
|---|---|---|
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `create_goal_plan(goal*: string, target_date: string, hours_per_week: number, notes: string)` | 🟡 write | Decompose a goal into milestones and tasks and save them. |
| `list_goals()` | 🟢 read | List active goals with progress. |
| `replan_goal(goal_id*: integer)` | 🟡 write | Adaptive re-plan: push overdue tasks of a goal forward. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |

## Daily Planner agent

You plan the user's day and week, recover from overdue work and run reviews.

| Tool | Risk | Purpose |
|---|---|---|
| `get_calendar_events(start_date: string, end_date: string)` | 🟢 read | List calendar events in a date range (syncs Google Calendar if connected). |
| `check_schedule_conflicts(date*: string, start_time*: string, end_time*: string)` | 🟢 read | Check whether a time range collides with existing events. |
| `find_free_slots(date: string, duration_hours: number, work_start: string, work_end: string)` | 🟢 read | Find free windows on a day. |
| `schedule_meeting(title*: string, date*: string, start_time*: string, end_time: string, duration_hours: number, attendees: string, description: string, with_meet: boolean, allow_conflict: boolean)` | write / external (depends on arguments) | Create a meeting with an automatic video link (Google Meet if connected, else Jitsi). Refuses on conflicts and suggests free slots. |
| `add_task_to_calendar(task_id*: integer, date: string, start_time: string, end_time: string)` | 🟡 write | Time-block an existing task on the calendar. |
| `reschedule_event(event_id*: integer, date: string, start_time: string, end_time: string)` | 🟡 write | Move an event. |
| `delete_event(event_id*: integer)` | 🟡 write | Delete an event. |
| `generate_meeting_link(event_id*: integer)` | 🟡 write | Attach a video-meeting link to an event. |
| `get_collaborators(search: string)` | 🟢 read | Search the user's collaborators. |
| `add_collaborators_to_event(event_id*: integer, collaborators*: string)` | 🟡 write | Add collaborators as attendees of an event. |
| `remember(content*: string, kind: string, importance: integer)` | 🟡 write | Save a durable fact, preference, habit or lesson about the user. |
| `recall(query*: string, limit: integer)` | 🟢 read | Search long-term memory. |
| `generate_daily_plan(date: string, work_start: string, work_end: string)` | 🟢 read | Build an overlap-free schedule for a day around fixed events, by priority and deadline. |
| `apply_daily_plan(date: string)` | 🟡 write | Write the saved plan for a date onto the calendar and tasks. |
| `reschedule_overdue()` | 🟡 write | Spread overdue tasks over the coming working days by priority. |
| `weekly_review()` | 🟢 read | Reflect on the past week (metrics, wins, slips, lesson). |
| `get_productivity_insights()` | 🟢 read | Metrics and rule-based insights about workload and progress. |
| `create_task(title*: string, description: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, kind: string, category: string, goal_id: integer)` | 🟡 write | Create a task/to-do on the workboard (optionally time-boxed). |
| `list_tasks(status: string, priority: string, limit: integer)` | 🟢 read | List workboard tasks. |
| `complete_task(task_id: integer, title: string)` | 🟡 write | Mark a task done by id or title. |
| `update_task(task_id*: integer, title: string, status: string, priority: string, due_date: string, scheduled_date: string, start_time: string, end_time: string, estimated_hours: number, description: string)` | 🟡 write | Change fields of a task. |
| `delete_task(task_id*: integer)` | 🟡 write | Delete a task permanently. |
| `assign_task(task_id*: integer, collaborator*: string)` | 🟡 write | Assign a task to one of the user's collaborators. |
