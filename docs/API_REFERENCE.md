# Synapsis Analytics Agent — API Reference

> Complete reference for every REST endpoint and WebSocket protocol in the Synapsis backend.
> Base URL: `http://localhost:7777`

---

## Table of Contents

1. [Health & Configuration](#1-health--configuration)
2. [Sessions](#2-sessions)
3. [Messages & History](#3-messages--history)
4. [Chat (WebSocket)](#4-chat-websocket)
5. [Query (Stateless)](#5-query-stateless)
6. [Agents](#6-agents)
7. [Workflows](#7-workflows)
8. [Workflow Execution (WebSocket)](#8-workflow-execution-websocket)
9. [Dashboard](#9-dashboard)
10. [Memories](#10-memories)
11. [Files](#11-files)
12. [Search](#12-search)
13. [Export](#13-export)
14. [Git](#14-git)
15. [Transcribe](#15-transcribe)
16. [Workflow Runs](#16-workflow-runs)
17. [Error Handling](#17-error-handling)

---

## 1. Health & Configuration

### `GET /api/health`

Basic health check. Used by AWS Lambda to determine container liveness.

**Response:**
```json
{
  "status": "ok",
  "model": "claude-opus-4-6",
  "workspace": "/Users/me/workspace",
  "auth_method": "subscription",
  "version": "2.0.0"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` if the server is running |
| `model` | string | Primary Claude model ID |
| `workspace` | string | Absolute path to the working directory |
| `auth_method` | string | `"subscription"` (Claude Code ~/.claude) or `"api_key"` (ANTHROPIC_API_KEY) or `"none"` |
| `version` | string | App version from FastAPI metadata |

---

### `GET /api/activity`

Container activity metrics. Called by the AWS cleanup Lambda every 5 minutes to decide whether to stop idle containers.

**Response:**
```json
{
  "active_connections": 1,
  "last_activity": 1711670400.0,
  "active_sessions": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `active_connections` | int | Number of open WebSocket connections right now |
| `last_activity` | float | Unix timestamp of the most recent WebSocket message |
| `active_sessions` | int | Number of in-memory SDK client sessions |

---

### `GET /api/config`

Full application configuration. Used by the frontend to adapt its UI (e.g., show VNC viewer, list memory categories).

**Response:**
```json
{
  "model": "claude-opus-4-6",
  "fallback_model": "claude-sonnet-4-5-20250929",
  "max_turns": 200,
  "auth_method": "subscription",
  "version": "2.0.0",
  "agent_type": "analytics",
  "personas": ["data_analysis", "visualization_reporting", "research_methodology", "code_automation", "computer_use"],
  "memory_categories": ["user_profile", "project_context", "analysis_decision", "methodology_note", "best_practice", "escalation_record"],
  "vnc_available": false,
  "vnc_port": 6081,
  "platform": "macos"
}
```

---

## 2. Sessions

### `GET /api/sessions`

List all chat sessions, ordered by pinned status (pinned first) then by most recently updated.

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "a1b2c3d4",
      "title": "Sales data analysis",
      "created_at": "2026-03-28T10:00:00",
      "updated_at": "2026-03-28T14:30:00",
      "model": "claude-opus-4-6",
      "message_count": 24,
      "pinned": true
    }
  ]
}
```

---

### `PATCH /api/sessions/{session_id}`

Rename a session.

**Request body:**
```json
{
  "title": "New Session Title"
}
```

**Response:**
```json
{
  "status": "updated",
  "session_id": "a1b2c3d4"
}
```

---

### `POST /api/sessions/{session_id}/pin`

Toggle the pinned/starred status of a session. Pinned sessions sort to the top of the list.

**Request body:**
```json
{
  "pinned": true
}
```

**Response:**
```json
{
  "status": "updated",
  "pinned": true
}
```

---

### `POST /api/sessions/{session_id}/auto-title`

Auto-generate a title from the first user message in the session. Strips common prefixes ("can you", "please", etc.), takes the first sentence, and capitalizes it. Does **not** override manually set titles.

**Response:**
```json
{
  "title": "Analyze the quarterly revenue trends",
  "session_id": "a1b2c3d4"
}
```

---

### `DELETE /api/sessions/{session_id}`

Delete a session and all its messages. Also cleans up the in-memory SDK client if one exists.

**Response:**
```json
{
  "status": "deleted"
}
```

---

### `DELETE /api/history`

Nuclear option — clears **all** messages and sessions from the database.

**Response:**
```json
{
  "status": "cleared"
}
```

---

## 3. Messages & History

### `GET /api/history/{session_id}`

Fetch the complete message history for a specific session, ordered by timestamp.

**Response:**
```json
{
  "messages": [
    { "type": "user", "content": "Analyze this CSV" },
    { "type": "text", "content": "I'll start by reading the file..." },
    { "type": "tool_use", "tool": "Read", "input": {"file_path": "/workspace/uploads/data.csv"}, "tool_use_id": "tu_abc123" },
    { "type": "tool_result", "tool_use_id": "tu_abc123", "content": "col1,col2,col3\n1,2,3\n...", "is_error": false },
    { "type": "text", "content": "The dataset has 3 columns..." },
    { "type": "result", "estimated_cost": 0.05, "turns": 3, "duration_ms": 12000, "is_error": false }
  ],
  "session_id": "a1b2c3d4"
}
```

**Message types stored in the database:**

| Type | Fields | Description |
|------|--------|-------------|
| `user` | `content` | User's input message |
| `text` | `content` | Assistant's text response |
| `thinking` | `content` | Assistant's internal reasoning (extended thinking) |
| `tool_use` | `tool`, `input`, `tool_use_id` | Tool invocation by the agent |
| `tool_result` | `tool_use_id`, `content` (max 8000 chars), `is_error` | Result returned by the tool |
| `system` | `subtype`, `data` | System notifications (init, agent_activity, etc.) |
| `result` | `estimated_cost`, `turns`, `duration_ms`, `is_error`, `error_detail` | Turn completion summary |

---

### `GET /api/history`

Backward-compatible endpoint — returns messages from the most recent session.

**Response:** Same as `GET /api/history/{session_id}` but `session_id` may be `null` if no sessions exist.

---

## 4. Chat (WebSocket)

### `WebSocket /ws/chat`

The primary real-time interface. Supports multi-session streaming with full agent orchestration.

#### Client → Server Messages

**Send a message:**
```json
{"message": "Analyze the sales data in uploads/sales.csv"}
```

**Create a new session:**
```json
{"type": "new_session"}
```

**Switch to an existing session:**
```json
{"type": "switch_session", "session_id": "a1b2c3d4"}
```

**Cancel an in-flight response:**
```json
{"type": "cancel", "session_id": "a1b2c3d4"}
```

**Retry with a different model** (after AUP error):
```json
{"type": "retry_with_model", "message": "original message", "model": "claude-sonnet-4-5-20250929"}
```

---

#### Server → Client Messages

All server messages include a `session_id` field identifying which session they belong to.

**Session assignment** (sent on connect or session switch):
```json
{"type": "session", "session_id": "a1b2c3d4"}
```

**Streamed text** (sent as deltas while the agent is generating):
```json
{"type": "text", "content": "partial text chunk...", "session_id": "a1b2c3d4"}
```

**Streamed thinking** (extended thinking deltas):
```json
{"type": "thinking", "content": "reasoning chunk...", "session_id": "a1b2c3d4"}
```

**Tool invocation** (sent when the agent calls a tool):
```json
{
  "type": "tool_use",
  "tool": "Bash",
  "input": {"command": "python analyze.py"},
  "tool_use_id": "tu_abc123",
  "session_id": "a1b2c3d4"
}
```

**Tool result** (sent when the tool returns):
```json
{
  "type": "tool_result",
  "tool_use_id": "tu_abc123",
  "content": "Analysis complete. Found 3 significant trends...",
  "is_error": false,
  "session_id": "a1b2c3d4"
}
```

**Sub-agent activity** (sent when the orchestrator delegates to a specialist):
```json
{
  "type": "agent_activity",
  "agent": "data_analysis",
  "status": "started",
  "tool_use_id": "tu_task_456",
  "session_id": "a1b2c3d4"
}
```

**System notifications:**
```json
{
  "type": "system",
  "subtype": "init",
  "data": "Session initialized",
  "session_id": "a1b2c3d4"
}
```

**Turn result** (sent when the agent finishes responding):
```json
{
  "type": "result",
  "estimated_cost": 0.05,
  "turns": 3,
  "duration_ms": 12000,
  "is_error": false,
  "error_detail": "",
  "auth_method": "subscription",
  "session_id": "a1b2c3d4"
}
```

**Session complete** (all processing for this turn is done):
```json
{"type": "session_complete", "session_id": "a1b2c3d4"}
```

**AUP/policy error** (content policy violation detected):
```json
{
  "type": "aup_error",
  "message": "Unable to respond due to usage policy...",
  "fallback_model": "claude-sonnet-4-5-20250929",
  "session_id": "a1b2c3d4"
}
```

**Cancellation confirmed:**
```json
{"type": "cancelled", "session_id": "a1b2c3d4"}
```

**Error:**
```json
{"type": "error", "message": "Connection lost", "session_id": "a1b2c3d4"}
```

---

**Cross-device session list refresh** (another device modified a session):
```json
{"type": "sessions_changed"}
```

**Cross-device session update** (a specific session was renamed, deleted, etc.):
```json
{"type": "session_update", "action": "deleted", "session_id": "a1b2c3d4"}
```

---

#### Session Lifecycle

1. **Connect** → Server assigns a session (new or most recent)
2. **Send message** → Server creates SDK client if needed, streams response
3. **Switch session** → Server loads a different session's client (or creates one with resume)
4. **Disconnect** → In-memory client stays alive; reconnecting and switching back resumes it
5. **Session resumption** → `claude_session_id` (SDK's internal UUID) is persisted to SQLite, enabling context restoration after server restart

#### Multi-Session Streaming Behavior

A single WebSocket carries messages for ALL sessions, each tagged with `session_id`. The frontend filters messages to the active session and routes background messages to a cache:

| Message arrives for | `activeSession` state | Frontend behavior |
|---|---|---|
| Active session | Set, matches | Processed into chat store normally |
| Background session (text/thinking) | Set, doesn't match | Appended to `_sessionCache` for that session |
| Background session (tool_use/tool_result) | Set, doesn't match | Cache invalidated; switch-back reloads from DB |
| Background session (result/cancelled) | Set, doesn't match | Cache invalidated; session marked complete |
| Any session | `null` (new chat transition) | Treated as background; NOT processed into UI |

**Concurrency:** Per-session `asyncio.Lock` in `session_manager.py` prevents concurrent `client.query()` calls from multiple WebSocket connections viewing the same session.

**Broadcasting:** Session rename, delete, and new message events are broadcast to all connected WebSocket clients via `sessions_changed` / `session_update` messages so all devices stay in sync.

---

## 5. Query (Stateless)

### `POST /api/query`

One-shot stateless query. Creates a fresh agent, runs the query, returns the result. No session persistence — useful for programmatic integrations.

**Request body:**
```json
{
  "message": "What is the p-value threshold for significance?"
}
```

| Field | Type | Constraints |
|-------|------|-------------|
| `message` | string | Required, 1–50,000 characters |
| `scope` | object | Optional active data scope — `{"years": [2024], "programs": ["SP09 — Scaling for Impact"]}`. Invalid values → `422`. |

**Response:**
```json
{
  "response": "The conventional threshold is p < 0.05...",
  "tool_uses": [
    {"tool": "WebSearch", "input": {"query": "p-value significance threshold"}}
  ],
  "result": {
    "estimated_cost": 0.02,
    "turns": 1,
    "duration_ms": 3500
  },
  "scope": {"years": [], "programs": []},
  "scope_description": "no filters (full portfolio)"
}
```

---

## 5b. Active data scope (agent filters)

The **scope** is a user-set year / programme filter that constrains the AGENT,
not a chart: the backend renders it into a delimited preamble prepended to the
message handed to the SDK, instructing the agent to apply the filter inside its
PRMS queries and to STATE the active scope in its answer (see
`synapsis/scope.py`). It is accepted by `POST /api/query` (above) and by the
chat WebSocket frame `{"message": "...", "scope": {...}}`. An absent or empty
scope is a strict no-op — the agent sees exactly the user's text.

### `GET /api/scope/options`

Returns the values the filter UI offers. **Auth required.**

```json
{
  "years": [2022, 2023, 2024, 2025],
  "programs": [
    {"code": "SP09", "label": "SP09 — Scaling for Impact",
     "era": "Programs & Accelerators (2025+)"}
  ],
  "source": "prms"
}
```

Programmes come from the PRMS `clarisa_initiatives` table, grouped by portfolio
era (Initiatives 2022–2024 vs Programs & Accelerators 2025+). `source` is
`"fallback"` when the PRMS database is unreachable and the static Science-Program
list was used instead.

---

## 6. Agents

### `GET /api/agents`

List all available specialist sub-agents.

**Response:**
```json
{
  "agents": [
    {
      "id": "data_analysis",
      "name": "Data Analysis",
      "description": "Statistical analysis, EDA, hypothesis testing, regression, data wrangling",
      "type": "Data Science",
      "status": "active",
      "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
      "model": "sonnet",
      "color": 220
    }
  ]
}
```

| Agent ID | Name | Specialization |
|----------|------|---------------|
| `data_analysis` | Data Analysis | EDA, hypothesis testing, regression, time series, causal inference |
| `visualization_reporting` | Visualization & Reporting | Matplotlib, Seaborn, Plotly, HTML/PDF/DOCX reports |
| `research_methodology` | Research Methodology | RCT, DiD, RDD, PSM, IV, sampling, power analysis |
| `code_automation` | Code & Automation | ETL, web scraping, API integration, file conversion |
| `computer_use` | Computer Use | GUI interaction, browsers, document editors, screenshots |

---

### `GET /api/agents/{agent_id}`

Get detailed information about a specific agent, including its full system prompt.

**Response:**
```json
{
  "id": "data_analysis",
  "description": "Statistical analysis, EDA, hypothesis testing...",
  "prompt": "You are the Data Analysis specialist...",
  "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
  "model": "sonnet"
}
```

---

## 7. Workflows

Workflows are multi-agent pipelines — ordered sequences of agents where each agent's output becomes the next agent's input.

### `GET /api/workflows`

List all workflows, ordered by creation date (newest first).

**Response:**
```json
{
  "workflows": [
    {
      "id": "wf-a1b2c3",
      "name": "Data → Visualization Pipeline",
      "description": "Analyze dataset then generate charts",
      "status": "completed",
      "progress": 100,
      "steps": 2,
      "created": "2026-03-28T10:00:00",
      "lastRun": "2026-03-28T14:00:00",
      "runCount": 3,
      "agentSequence": ["data_analysis", "visualization_reporting"],
      "initialPrompt": "Analyze sales data and create charts",
      "nodes": [{"id": "n1", "label": "Data Analysis", ...}],
      "edges": [{"id": "e1", "source": "n1", "target": "n2"}]
    }
  ]
}
```

**Workflow status values:** `draft`, `running`, `completed`, `failed`, `cancelled`

---

### `POST /api/workflows`

Create a new workflow.

**Request body:**
```json
{
  "name": "Analysis Pipeline",
  "description": "Full data analysis with report generation",
  "agentSequence": ["data_analysis", "visualization_reporting"],
  "initialPrompt": "Analyze the CSV in uploads/ and create a report",
  "nodes": [],
  "edges": []
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-readable name |
| `description` | string | No | What the pipeline does |
| `agentSequence` | string[] | Yes | Ordered list of agent IDs |
| `initialPrompt` | string | No | Default prompt for pipeline runs |
| `nodes` | array | No | React Flow node positions for visual editor |
| `edges` | array | No | React Flow edge definitions |

**Response:** The created workflow object.

---

### `GET /api/workflows/{workflow_id}`

Get a single workflow by ID.

---

### `DELETE /api/workflows/{workflow_id}`

Delete a workflow.

**Response:**
```json
{"status": "deleted"}
```

---

### `POST /api/workflows/{workflow_id}/run`

Mark a workflow as running. This updates the status in the database. **Actual execution** happens via the WebSocket endpoint `/ws/workflow/{workflow_id}`.

**Response:**
```json
{
  "status": "started",
  "workflow": { ... }
}
```

---

## 8. Workflow Execution (WebSocket)

### `WebSocket /ws/workflow/{workflow_id}`

Executes a multi-agent pipeline with real-time streaming of each step.

#### Client → Server

**Start execution:**
```json
{"type": "run", "prompt": "Analyze the dataset and create visualizations"}
```

**Cancel execution:**
```json
{"type": "cancel"}
```

**Keep-alive:**
```json
{"type": "ping"}
```

---

#### Server → Client

**Step started:**
```json
{
  "type": "step_start",
  "step": 0,
  "agent_id": "data_analysis",
  "agent_name": "Data Analysis",
  "total_steps": 2
}
```

**Streaming content** (same types as chat, but with `step` field):
```json
{"type": "text", "content": "...", "step": 0}
{"type": "thinking", "content": "...", "step": 0}
{"type": "tool_use", "tool": "Bash", "input": {...}, "tool_use_id": "...", "step": 0}
{"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": false, "step": 0}
```

**Step turn result:**
```json
{
  "type": "result",
  "estimated_cost": 0.03,
  "turns": 2,
  "duration_ms": 8000,
  "session_id": "...",
  "is_error": false,
  "step": 0
}
```

**Step completed:**
```json
{
  "type": "step_complete",
  "step": 0,
  "agent_id": "data_analysis",
  "agent_name": "Data Analysis",
  "output_preview": "Found 3 significant trends in the data...",
  "duration_s": 8.5
}
```

**Pipeline completed:**
```json
{
  "type": "pipeline_complete",
  "total_steps": 2,
  "total_duration_s": 20.3
}
```

**Pipeline cancelled:**
```json
{
  "type": "pipeline_cancelled",
  "completed_steps": 1
}
```

**Error:**
```json
{
  "type": "error",
  "message": "Agent timeout",
  "step": 1
}
```

---

#### Execution Flow

```
Step 0: data_analysis
  Input: user's initial prompt
  Output: analysis text → becomes input for step 1

Step 1: visualization_reporting
  Input: "Previous agent (Data Analysis) produced:\n\n{step 0 output}\n\nNow continue..."
  Output: visualization results

Pipeline complete.
```

Each step creates a **fresh SDK client** with that agent's system prompt, preventing context contamination between agents.

---

## 9. Dashboard

### `GET /api/dashboard/stats`

Aggregated statistics for the dashboard page.

**Response:**
```json
{
  "stats": [
    {"label": "Active Sessions", "value": 5, "trend": 0, "trendUp": true},
    {"label": "Total Agents", "value": 5, "trend": 0, "trendUp": true},
    {"label": "Messages", "value": 247, "trend": 0, "trendUp": true},
    {"label": "Memories Stored", "value": 18, "trend": 0, "trendUp": true},
    {"label": "Sessions Total", "value": 12, "trend": 0, "trendUp": true},
    {"label": "Recent Activity (7d)", "value": 34, "trend": 0, "trendUp": true}
  ],
  "agent_count": 5,
  "active_connections": 1
}
```

---

### `GET /api/dashboard/activity`

Message activity over time, used for the activity chart.

**Query parameters:**

| Param | Type | Default | Constraints |
|-------|------|---------|-------------|
| `days` | int | 7 | 1–90 |

**Response:**
```json
{
  "activity": [
    {"date": "Mon", "messages": 12},
    {"date": "Tue", "messages": 8},
    {"date": "Wed", "messages": 0},
    {"date": "Thu", "messages": 15},
    {"date": "Fri", "messages": 23},
    {"date": "Sat", "messages": 5},
    {"date": "Sun", "messages": 3}
  ]
}
```

Returns a **gapless series** — days with no messages get `messages: 0` rather than being omitted. This keeps charts evenly spaced.

---

## 10. Memories

The persistent memory system allows the agent to store and recall context across sessions. Memories are stored in SQLite with FTS5 full-text search indexing.

### `GET /api/memories`

List all active (non-deleted) memories, sorted by importance (highest first) then by last updated.

**Response:**
```json
{
  "memories": [
    {
      "id": 1,
      "category": "best_practice",
      "content": "Always check data distributions before running parametric tests",
      "importance": 8,
      "tags": "statistics, data quality",
      "created_at": 1711670400.0,
      "updated_at": 1711670400.0,
      "access_count": 5,
      "source_session": "a1b2c3d4"
    }
  ]
}
```

**Memory categories:**

| Category | Purpose |
|----------|---------|
| `user_profile` | User preferences, working style, background |
| `project_context` | Project parameters, data descriptions, constraints |
| `analysis_decision` | Key analysis choices and their rationale |
| `methodology_note` | Reference values, formulas, domain facts |
| `best_practice` | General analytics best practices |
| `escalation_record` | Expert handoff records |

---

### `POST /api/memories`

Create a new memory manually (the agent also creates memories via the MCP tool during conversations).

**Request body:**
```json
{
  "category": "project_context",
  "content": "The client uses fiscal year starting April 1",
  "importance": 7,
  "tags": "client, fiscal year",
  "source_session": "api"
}
```

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `category` | string | `"fact"` | One of the 6 categories |
| `content` | string | — | Required, min 1 char |
| `importance` | int | 5 | 1–10 (10 = critical) |
| `tags` | string | `""` | Comma-separated keywords |
| `source_session` | string | `"api"` | Session that created it |

**Response:**
```json
{
  "id": 42,
  "status": "created"
}
```

---

### `DELETE /api/memories/{memory_id}`

Soft-delete a memory (sets `active = 0`). The row is preserved for audit history but excluded from all queries.

**Response:**
```json
{
  "status": "deleted"
}
```

---

### MCP Tools (used by the agent internally)

These are invoked by the agent during conversations, not by external clients:

| Tool | Purpose |
|------|---------|
| `mcp__synapsis__memory_store` | Save a memory (de-duplicates by category + content) |
| `mcp__synapsis__memory_recall` | FTS5 search with optional category filter; bumps `access_count` |
| `mcp__synapsis__memory_list` | List memories sorted by importance |
| `mcp__synapsis__memory_forget` | Soft-delete by ID |
| `mcp__synapsis__agent_create` | Create a new custom specialist agent (name, description, system_prompt, tools, model). Persisted to DB and available for routing immediately. |
| `mcp__synapsis__agent_list` | List all available agents (builtin and custom). Optional `include_prompts` parameter to show system prompt previews. |
| `mcp__synapsis__agent_update` | Update a custom agent's configuration (name, description, system_prompt, tools, model). Cannot modify builtin agents. |

At the start of each session, the **top 20 memories** (by importance) are automatically injected into the agent's context.

---

## 11. Files

### `POST /api/upload`

Upload a file to the workspace.

**Request:** Multipart form data with a `file` field.

```bash
curl -X POST http://localhost:7777/api/upload \
  -F "file=@data.csv"
```

**Security:** Filenames are sanitized — directory traversal (`../`) and dotfiles (`.env`) are rejected.

**Response:**
```json
{
  "path": "uploads/data.csv",
  "size": 24500
}
```

Files are saved to `{WORKSPACE}/uploads/{sanitized_filename}`.

---

### `GET /api/files`

List all non-hidden files in the workspace recursively.

**Response:**
```json
{
  "files": [
    {
      "name": "uploads/data.csv",
      "size": 24500,
      "modified": "2026-03-28T14:30:00"
    },
    {
      "name": "analysis/results.html",
      "size": 18200,
      "modified": "2026-03-28T15:00:00"
    }
  ]
}
```

---

### `GET /api/files/{filename:path}`

Download a file from the workspace.

**Security:** Path traversal is blocked — the resolved path must be within the workspace directory.

```bash
curl -O http://localhost:7777/api/files/uploads/data.csv
```

**Response:** Streaming `FileResponse` with appropriate MIME type.

---

## 12. Search

### `GET /api/search`

Search across all conversations for a keyword.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | — | Required search keyword |
| `limit` | int | 50 | Max results |

```bash
curl "http://localhost:7777/api/search?q=regression&limit=20"
```

**Response:**
```json
{
  "results": [
    {
      "session_id": "a1b2c3d4",
      "session_title": "Sales Analysis",
      "message_type": "text",
      "snippet": "...running a linear regression on the quarterly...",
      "timestamp": 1711670400.0
    }
  ],
  "query": "regression"
}
```

Searches `user` and `text` message types using SQL `LIKE` with wildcards. Snippets include ±60 characters of context around the match.

---

## 13. Export

### `GET /api/export/{session_id}`

Export a session's conversation in various formats.

**Query parameters:**

| Param | Type | Default | Options |
|-------|------|---------|---------|
| `format` | string | `"md"` | `md`, `html`, `docx`, `pdf` |
| `detail` | string | `"standard"` | `standard`, `full` |

**Detail levels:**
- `standard` — User messages + assistant text + tool names (no tool I/O details)
- `full` — Everything including thinking blocks, tool inputs/outputs, system messages

```bash
# Markdown export
curl -O "http://localhost:7777/api/export/a1b2c3d4?format=md&detail=full"

# Word document
curl -O "http://localhost:7777/api/export/a1b2c3d4?format=docx"

# PDF
curl -O "http://localhost:7777/api/export/a1b2c3d4?format=pdf"
```

**Response:** `FileResponse` with the appropriate MIME type and a safe filename like `Sales_Analysis_a1b2c3d4.md`.

**Export rendering:**
- **Markdown:** Emoji-prefixed sections (🧑 User, 🤖 Assistant, 🔧 Tool, etc.)
- **HTML:** Self-contained with inline CSS and colorized message types
- **DOCX:** python-docx with colored headings and formatting
- **PDF:** Rendered via Chromium or wkhtmltopdf; falls back to HTML if neither is available

---

## 14. Git

Repository information endpoints. All endpoints require the workspace (or a parent/child directory) to be a git repository. Returns `422` if no git repository is found.

### `GET /api/git/status`

Current branch, staged/unstaged/untracked files, and ahead/behind counts.

**Response:**
```json
{
  "branch": "main",
  "staged": [
    {"path": "src/app.py", "status": "M"}
  ],
  "unstaged": [
    {"path": "README.md", "status": "M"}
  ],
  "untracked": ["new_file.txt"],
  "ahead": 1,
  "behind": 0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `branch` | string | Current branch name |
| `staged` | array | Files staged for commit, each with `path` and `status` (M=modified, A=added, D=deleted, R=renamed) |
| `unstaged` | array | Modified but unstaged files, each with `path` and `status` |
| `untracked` | string[] | Untracked file paths |
| `ahead` | int | Commits ahead of upstream |
| `behind` | int | Commits behind upstream |

---

### `GET /api/git/diff`

Unified diff for a specific file or the entire working tree. When a file is specified, also returns old and new file content for side-by-side diffing.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | string | `null` | Path to a specific file (relative to repo root). Omit for full working-tree diff. |
| `staged` | bool | `false` | Show staged (cached) diff instead of working-tree diff |

**Response (with file specified):**
```json
{
  "diff": "--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,4 @@\n...",
  "file": "README.md",
  "old_content": "original file content...",
  "new_content": "modified file content..."
}
```

**Response (no file specified):**
```json
{
  "diff": "diff --git a/README.md b/README.md\n...",
  "file": null,
  "old_content": null,
  "new_content": null
}
```

**Security:** Path traversal is blocked -- the resolved file path must be within the repository root.

---

### `GET /api/git/log`

Recent commit history.

**Query parameters:**

| Param | Type | Default | Constraints |
|-------|------|---------|-------------|
| `limit` | int | 20 | 1--500 |

**Response:**
```json
{
  "commits": [
    {
      "hash": "a1b2c3d4e5f6...",
      "short_hash": "a1b2c3d",
      "author": "Jane Doe",
      "email": "jane@example.com",
      "relative_date": "2 hours ago",
      "message": "Add data pipeline for sales ETL"
    }
  ]
}
```

---

### `GET /api/git/show`

File content at a specific git ref (branch, tag, or commit hash).

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | string | -- | **Required.** File path relative to repo root. |
| `ref` | string | `"HEAD"` | Git ref (branch name, tag, or commit hash) |

**Response:**
```json
{
  "file": "src/app.py",
  "ref": "HEAD",
  "content": "import sys\n..."
}
```

**Security:** The `ref` parameter is validated against a strict regex pattern (`^[\w./@^~{}\-]+$`) to prevent shell injection.

---

## 15. Transcribe

Voice-to-text transcription powered by OpenAI's `gpt-4o-transcribe` model. Requires the `OPENAI_API_KEY` environment variable to be set.

### `POST /api/transcribe`

Transcribe an audio file to text.

**Request:** Multipart form data with a `file` field containing the audio.

```bash
curl -X POST http://localhost:7777/api/transcribe \
  -F "file=@recording.webm"
```

**Response:**
```json
{
  "text": "Analyze the quarterly revenue trends for Q1 2026"
}
```

| Status | Condition |
|--------|-----------|
| `200` | Transcription successful |
| `500` | `OPENAI_API_KEY` not set, or `httpx` not installed |
| `502` | OpenAI API returned an error |

**Notes:**
- The audio file is saved to a temporary file during processing and deleted after the request completes.
- Uses `httpx.AsyncClient` with a 60-second timeout for the OpenAI API call.
- Supported audio formats: any format accepted by the OpenAI transcription API (webm, mp3, wav, m4a, etc.).

---

## 16. Workflow Runs

Persistent history of workflow pipeline executions. Run data is stored in a separate SQLite database (`workflow_runs.db`) alongside the main `chat.db`.

### `GET /api/workflows/{workflow_id}/runs`

List all runs for a specific workflow.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Maximum number of runs to return |
| `offset` | int | 0 | Pagination offset |

**Response:**
```json
{
  "runs": [
    {
      "id": "run-abc123",
      "workflow_id": "wf-a1b2c3",
      "workflow_name": "Data Pipeline",
      "status": "completed",
      "agent_sequence": ["data_analysis", "visualization_reporting"],
      "started_at": 1711670400.0,
      "completed_at": 1711670420.0
    }
  ],
  "total": 1
}
```

---

### `GET /api/workflows/{workflow_id}/runs/{run_id}`

Get full run detail including steps and their messages.

**Response:**
```json
{
  "id": "run-abc123",
  "workflow_id": "wf-a1b2c3",
  "workflow_name": "Data Pipeline",
  "status": "completed",
  "agent_sequence": ["data_analysis", "visualization_reporting"],
  "steps": [
    {
      "step_index": 0,
      "agent_id": "data_analysis",
      "status": "completed",
      "messages": [
        {"type": "text", "data": {"content": "Analyzing the dataset..."}}
      ]
    }
  ]
}
```

---

### `GET /api/workflows/{workflow_id}/runs/{run_id}/download`

Download a workflow run log in various formats.

**Query parameters:**

| Param | Type | Default | Options |
|-------|------|---------|---------|
| `format` | string | `"json"` | `json`, `md`, `html` |

**Response:** File download with the appropriate MIME type.

- **json** -- Full run data as JSON (prefers on-disk log file if available; falls back to DB reconstruction)
- **md** -- Markdown-formatted run log
- **html** -- Self-contained HTML report

---

### `POST /api/workflows/{workflow_id}/runs/{run_id}/continue`

Create a new chat session pre-seeded with the workflow run's output context. This allows users to continue an analysis conversation from where a workflow pipeline left off.

**Response:**
```json
{
  "session_id": "b2c3d4e5",
  "title": "Continue: Data Pipeline"
}
```

The new session includes a system message with the workflow context, and the context is also stored for injection into the first Claude SDK query so the agent has full awareness of the pipeline output.

---

## 17. Error Handling

### HTTP Errors

All endpoints return standard HTTP status codes:

| Code | When |
|------|------|
| `200` | Success |
| `400` | Invalid request (bad JSON, missing fields, validation failure) |
| `404` | Session/workflow/memory/file not found |
| `422` | Pydantic validation error (auto-generated by FastAPI) |
| `500` | Internal server error |

Error response format:
```json
{
  "detail": "Session not found"
}
```

---

### WebSocket Errors

**AUP/Content Policy Violations:**
When the agent's response triggers Anthropic's usage policy, the server sends:
```json
{
  "type": "aup_error",
  "message": "Unable to respond due to usage policy...",
  "fallback_model": "claude-sonnet-4-5-20250929",
  "session_id": "a1b2c3d4"
}
```
The client can retry with `{"type": "retry_with_model", "message": "...", "model": "..."}`.

**Context Window Exhaustion:**
When a conversation exceeds the model's context window:
```json
{
  "type": "result",
  "is_error": true,
  "error_detail": "This conversation has become too long for the model's context window...",
  "session_id": "a1b2c3d4"
}
```

**Safety Hook Blocks:**
Dangerous Bash commands (rm -rf /, fork bombs, DROP DATABASE, etc.) are blocked by the pre-tool safety hook. The agent receives a denial with a reason, which it can relay to the user.

---

## Appendix: Authentication

The server supports two authentication methods (checked in order):

1. **Claude Code Subscription** — Looks for `~/.claude` directory. No API key needed.
2. **API Key** — Uses `ANTHROPIC_API_KEY` environment variable.

There is no user-level authentication on the API endpoints. The system is designed for single-user or trusted-network deployment. For multi-user scenarios, the AWS deployment adds API Gateway with per-user provisioning.

---

## Appendix: Rate Limits & Constraints

| Constraint | Value |
|------------|-------|
| Max message length (query) | 50,000 characters |
| Max turns per session | 200 (configurable via `SYNAPSIS_MAX_TURNS`) |
| Tool result truncation | 8,000 characters |
| Memory importance range | 1–10 |
| Memory context injection | Top 20 by importance |
| Audit log input truncation | 500 characters |
| Audit log output truncation | 300 characters |
| Session ID length | 8 characters (UUID prefix) |
| WebSocket max message size | 1,000,000 bytes |
| Activity data max range | 90 days |
