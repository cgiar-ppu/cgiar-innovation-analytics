# CGIAR Innovation Analytics Platform -- API Reference

> REST and WebSocket API for the CGIAR Innovation Analytics Platform.
> Built on FastAPI with Claude Agent SDK, serving PRMS data analytics and AI-driven agricultural research insights.

**Base URL (DEV):**

```
https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com
```

**Custom domain (pending DNS):**

```
https://innovation-analytics-dev.synapsis-analytics.com
```

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [REST Endpoints](#3-rest-endpoints)
   - [GET /api/health](#get-apihealth)
   - [GET /api/config](#get-apiconfig)
   - [GET /api/agents](#get-apiagents)
   - [GET /api/dashboard/prms-stats](#get-apidashboardprms-stats)
   - [POST /api/query](#post-apiquery)
4. [WebSocket Protocol](#4-websocket-protocol)
   - [Connection](#connection)
   - [Client to Server Frames](#client--server-frames)
   - [Server to Client Frames](#server--client-frames)
   - [Session Management Flow](#session-management-flow)
   - [Error Handling](#error-handling)
5. [OpenAPI / Swagger](#5-openapi--swagger)
6. [Rate Limits and Quotas](#6-rate-limits-and-quotas)

---

## 1. Overview

The CGIAR Innovation Analytics Platform exposes a REST API and a WebSocket interface for real-time AI-assisted analysis of CGIAR research data. The platform connects to the PRMS (Planning and Reporting Management System) database, which contains approximately 27,800 active results across 197 tables covering innovations, knowledge products, initiatives, and partner networks.

Key capabilities:

- **Dashboard analytics** -- Pre-computed KPIs and chart data from PRMS.
- **AI chat** -- WebSocket-based streaming conversations powered by Claude, with access to PRMS query tools, chart generation, scenario analysis, and partner identification.
- **Stateless query** -- Single-shot REST endpoint for programmatic integrations.
- **Agent management** -- Browse, create, clone, and configure specialist AI agents.

All REST endpoints are prefixed with `/api`. The server is a FastAPI application running behind an AWS ALB with HTTPS termination on port 443.

---

## 2. Authentication

**Current implementation:** The platform authenticates to the Anthropic API using a server-side API key set via the `ANTHROPIC_API_KEY` environment variable. There is no client-facing authentication on API endpoints at this time.

**Planned:** AWS Cognito user pool integration is on the roadmap. Once implemented, all API and WebSocket requests will require a JWT bearer token issued by the Cognito user pool.

For the current deployment, the ALB provides network-level access control. Direct API access is available to authorized network clients without additional credentials.

---

## 3. REST Endpoints

### GET /api/health

Basic health check. Returns server status, active model, and authentication method. Used by AWS infrastructure (cleanup Lambda, ALB health checks) to determine container liveness.

**Parameters:** None

**Example request:**

```bash
curl https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api/health
```

**Example response:**

```json
{
  "status": "ok",
  "model": "claude-opus-4-6",
  "workspace": "/workspace",
  "auth_method": "api_key",
  "version": "2.0.0"
}
```

| Field         | Type   | Description                                                                 |
|---------------|--------|-----------------------------------------------------------------------------|
| `status`      | string | Always `"ok"` when the server is running                                    |
| `model`       | string | Primary Claude model identifier                                             |
| `workspace`   | string | Absolute path to the server's working directory                             |
| `auth_method` | string | `"api_key"` (ANTHROPIC_API_KEY) or `"subscription"` (Claude Code ~/.claude) |
| `version`     | string | Application version                                                         |

---

### GET /api/config

Full application configuration. Used by the frontend to adapt its UI, determine available agents, and display platform capabilities.

**Parameters:** None

**Example request:**

```bash
curl https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api/config
```

**Example response:**

```json
{
  "model": "claude-opus-4-6",
  "fallback_model": "claude-sonnet-4-5-20250929",
  "max_turns": 200,
  "auth_method": "api_key",
  "version": "2.0.0",
  "agent_type": "synapsis_analytics",
  "personas": [
    "prms_data_analyst",
    "innovation_strategy_advisor",
    "research_synthesizer",
    "report_generator",
    "data_analysis",
    "visualization_reporting",
    "research_methodology",
    "code_automation",
    "computer_use"
  ],
  "memory_categories": [
    "user_profile",
    "project_context",
    "analysis_decision",
    "methodology_note",
    "best_practice",
    "escalation_record"
  ],
  "vnc_available": false,
  "vnc_port": 6080,
  "platform": "cgiar"
}
```

| Field               | Type     | Description                                                  |
|---------------------|----------|--------------------------------------------------------------|
| `model`             | string   | Primary Claude model                                         |
| `fallback_model`    | string   | Model used for AUP policy fallback retries                   |
| `max_turns`         | integer  | Maximum agent turns per session                              |
| `auth_method`       | string   | Active authentication method                                 |
| `version`           | string   | Application version                                          |
| `agent_type`        | string   | Always `"synapsis_analytics"`                                |
| `personas`          | string[] | List of available agent IDs (builtin + CGIAR specialists)    |
| `memory_categories` | string[] | Valid categories for the persistent memory system            |
| `vnc_available`     | boolean  | Whether VNC-based computer use is available                  |
| `vnc_port`          | integer  | VNC WebSocket port (if available)                            |
| `platform`          | string   | Platform identifier (`"cgiar"`, `"macos"`, etc.)             |

---

### GET /api/agents

List all available AI agents, including builtin CGIAR specialists, the orchestrator, and any user-created custom agents. Builtin agents cannot be modified or deleted.

**Parameters:** None

**Example request:**

```bash
curl https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api/agents
```

**Example response:**

```json
{
  "agents": [
    {
      "id": "orchestrator",
      "name": "Orchestrator",
      "description": "Routes queries to the appropriate specialist agent",
      "type": "builtin",
      "status": "active",
      "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
      "model": "claude-opus-4-6",
      "color": "hsl(270, 70%, 50%)",
      "system_prompt": "",
      "tags": ["orchestrator"],
      "is_active": 1,
      "created_at": null,
      "updated_at": null,
      "parent_agent": "",
      "version": 1
    },
    {
      "id": "prms_data_analyst",
      "name": "PRMS Data Analyst",
      "description": "Specialist in querying the PRMS database with full 197-table schema reference",
      "type": "builtin",
      "status": "active",
      "tools": ["Read", "Bash", "Glob", "Grep"],
      "model": "sonnet",
      "color": "hsl(200, 70%, 50%)",
      "system_prompt": "...",
      "tags": ["cgiar", "prms", "data"],
      "is_active": 1,
      "created_at": null,
      "updated_at": null,
      "parent_agent": "",
      "version": 1
    }
  ]
}
```

Each agent object contains:

| Field           | Type     | Description                                                      |
|-----------------|----------|------------------------------------------------------------------|
| `id`            | string   | Unique agent identifier                                          |
| `name`          | string   | Display name                                                     |
| `description`   | string   | What the agent specializes in                                    |
| `type`          | string   | `"builtin"` or `"custom"`                                        |
| `status`        | string   | `"active"` or `"inactive"`                                       |
| `tools`         | string[] | List of tools available to the agent                             |
| `model`         | string   | Model identifier (`"sonnet"`, `"opus"`, or full model ID)        |
| `color`         | string   | HSL or hex color for UI display                                  |
| `system_prompt` | string   | The agent's system prompt (full text)                            |
| `tags`          | string[] | Categorization tags                                              |
| `is_active`     | integer  | 1 if active, 0 if soft-deleted                                   |
| `created_at`    | float    | Unix timestamp (null for builtin agents)                         |
| `updated_at`    | float    | Unix timestamp of last update (null for builtin agents)          |
| `parent_agent`  | string   | ID of the agent this was cloned from (empty if original)         |
| `version`       | integer  | Incremented on each update                                       |

**CGIAR-specific builtin agents:**

| Agent ID                      | Specialization                                                |
|-------------------------------|---------------------------------------------------------------|
| `prms_data_analyst`           | SQL queries against the PRMS database (197-table schema)      |
| `innovation_strategy_advisor` | Portfolio analysis, scenario modeling, strategic recommendations |
| `research_synthesizer`        | Cross-initiative pattern analysis and narrative synthesis      |
| `report_generator`            | Formatted reports with charts and structured output           |

**Additional endpoints:**

| Method | Path                          | Description                                  |
|--------|-------------------------------|----------------------------------------------|
| GET    | `/api/agents/{agent_id}`      | Get full details for a specific agent        |
| POST   | `/api/agents`                 | Create a custom agent                        |
| PUT    | `/api/agents/{agent_id}`      | Update a custom agent (builtin not allowed)  |
| DELETE | `/api/agents/{agent_id}`      | Soft-delete a custom agent                   |
| POST   | `/api/agents/{agent_id}/clone`| Clone any agent as a new custom agent        |
| POST   | `/api/agents/{agent_id}/test` | Validate an agent's configuration            |

---

### GET /api/dashboard/prms-stats

Returns live KPIs and chart data sourced from the PRMS SQLite database. Results are cached in-memory for 5 minutes since the PRMS snapshot is static. This is the primary data endpoint for the Innovation Analytics dashboard.

**Parameters:** None

**Example request:**

```bash
curl https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api/dashboard/prms-stats
```

**Example response:**

```json
{
  "kpis": {
    "total_results": 27803,
    "total_innovations": 4664,
    "innovation_uses": 559,
    "active_initiatives": 55,
    "countries_covered": 183,
    "knowledge_products": 12850
  },
  "charts": {
    "results_by_type": {
      "chartType": "pie",
      "title": "Results by Type",
      "description": "Distribution of 27,803 results across reporting categories",
      "xAxisKey": "type",
      "data": [
        { "type": "Knowledge Product", "count": 12850 },
        { "type": "Innovation Development", "count": 4664 },
        { "type": "Output", "count": 3200 },
        { "type": "Outcome", "count": 2100 }
      ],
      "series": [
        { "key": "count", "label": "Results", "color": "#427730" }
      ]
    },
    "top_countries": {
      "chartType": "bar",
      "title": "Top 10 Countries by Results",
      "description": "Countries with the highest number of reported results",
      "xAxisKey": "country",
      "data": [
        { "country": "Kenya", "count": 1520 },
        { "country": "India", "count": 1340 },
        { "country": "Ethiopia", "count": 1180 }
      ],
      "series": [
        { "key": "count", "label": "Results", "color": "#0065BD" }
      ]
    },
    "irl_distribution": {
      "chartType": "bar",
      "title": "Innovation Readiness Levels",
      "description": "Distribution of innovations across IRL 0-9 scale",
      "xAxisKey": "level",
      "data": [
        { "level": "Level 0 - Idea/concept", "count": 200 },
        { "level": "Level 1 - Basic research", "count": 450 }
      ],
      "series": [
        { "key": "count", "label": "Innovations", "color": "#7AB800" }
      ]
    },
    "top_initiatives": {
      "chartType": "bar",
      "title": "Top 10 Initiatives by Output",
      "description": "CGIAR initiatives with the most reported results",
      "xAxisKey": "initiative",
      "data": [
        { "initiative": "INIT-01", "count": 980 },
        { "initiative": "INIT-02", "count": 870 }
      ],
      "series": [
        { "key": "count", "label": "Results", "color": "#E37222" }
      ]
    }
  },
  "last_updated": "2026-05-22T14:30:00.000000+00:00"
}
```

**KPI fields:**

| Field                | Type    | Description                                      |
|----------------------|---------|--------------------------------------------------|
| `total_results`      | integer | Total active results in PRMS                     |
| `total_innovations`  | integer | Count of innovation development results          |
| `innovation_uses`    | integer | Count of innovations in use (result type 2)      |
| `active_initiatives` | integer | Distinct CGIAR initiatives with active results   |
| `countries_covered`  | integer | Distinct countries with associated results       |
| `knowledge_products` | integer | Results classified as knowledge products         |

**Chart object structure:**

Each chart in the `charts` object follows a consistent schema designed for direct rendering with Recharts on the frontend:

| Field         | Type     | Description                                              |
|---------------|----------|----------------------------------------------------------|
| `chartType`   | string   | `"pie"` or `"bar"`                                       |
| `title`       | string   | Chart title for display                                  |
| `description` | string   | Subtitle or explanatory text                             |
| `xAxisKey`    | string   | Key in each data item used for the x-axis / slice label  |
| `data`        | array    | Array of data objects                                    |
| `series`      | array    | Array of `{key, label, color}` objects defining series   |

**Error responses:**

| Status | Condition                        |
|--------|----------------------------------|
| 200    | Success (may include partial data if individual queries failed) |
| 503    | PRMS database file not found or database connection error       |

---

### POST /api/query

Stateless single-shot query endpoint. Creates a fresh agent instance, processes the message, and returns the complete response. No session state is maintained -- each request is independent. Suitable for programmatic integrations and automated pipelines.

**Request body:**

| Field     | Type   | Required | Constraints              |
|-----------|--------|----------|--------------------------|
| `message` | string | Yes      | 1--50,000 characters     |

**Example request:**

```bash
curl -X POST https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/api/query \
  -H "Content-Type: application/json" \
  -d '{"message": "How many innovations are at IRL level 4 or above?"}'
```

**Example response:**

```json
{
  "response": "Based on the PRMS database, there are 1,247 innovations at Innovation Readiness Level 4 or above. Here is the breakdown:\n\n- Level 4 (Tested/validated): 520\n- Level 5 (Refined): 312\n- Level 6 (Available for use): 198\n- Level 7 (Widely available): 127\n- Level 8 (Saturated): 56\n- Level 9 (Widely used): 34\n\nThese represent approximately 26.7% of all 4,664 documented innovations in the system.",
  "tool_uses": [
    {
      "tool": "prms_query",
      "input": {
        "query": "SELECT cirl.name AS level, COUNT(*) AS count FROM results_innovations_dev rid JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id WHERE rid.is_active = 1 AND cirl.id >= 4 GROUP BY cirl.name, cirl.id ORDER BY cirl.id",
        "question": "How many innovations are at IRL level 4 or above?"
      }
    }
  ],
  "result": {
    "estimated_cost": 0.04,
    "turns": 2,
    "duration_ms": 8500
  }
}
```

| Response Field    | Type    | Description                                               |
|-------------------|---------|-----------------------------------------------------------|
| `response`        | string  | Combined text output from the agent                       |
| `tool_uses`       | array   | List of tools the agent invoked, each with `tool` and `input` |
| `result.estimated_cost` | float | Estimated API cost in USD                            |
| `result.turns`    | integer | Number of agent turns (tool use cycles)                   |
| `result.duration_ms` | integer | Total processing time in milliseconds                 |

---

## 4. WebSocket Protocol

The WebSocket interface provides real-time, streaming AI conversations with full tool use visibility. It is the primary interface for the chat UI.

### Connection

**Endpoint:**

```
wss://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/ws/chat
```

The connection is accepted immediately upon upgrade. The server assigns a session (new or most recent) and sends a `session` frame. A single WebSocket connection multiplexes messages for all sessions -- each frame includes a `session_id` field.

**Additional WebSocket endpoints:**

| Endpoint                          | Description                              |
|-----------------------------------|------------------------------------------|
| `wss://<host>/ws/agent/{agent_id}`    | Direct interaction with a specific agent |
| `wss://<host>/ws/workflow/{workflow_id}` | Pipeline execution streaming          |
| `wss://<host>/ws/fleet/{fleet_id}`    | Multi-agent fleet streaming              |

### Client --> Server Frames

All client frames are JSON objects.

**Send a chat message:**

```json
{
  "message": "What are the top innovations in Kenya?"
}
```

When no explicit `type` field is present, the frame is treated as a user message. The server creates an SDK client for the session if one does not already exist, then streams the agent's response.

**Create a new session:**

```json
{
  "type": "new_session"
}
```

Starts a fresh conversation. The server responds with a `session` frame containing the new `session_id`. The previous session's in-memory client remains alive for potential resumption.

**Switch to an existing session:**

```json
{
  "type": "switch_session",
  "session_id": "a1b2c3d4"
}
```

Switches the connection's active session. If the target session has a running agent task, the connection attaches to its event stream and replays buffered events. The server responds with a `session` frame confirming the switch.

**Cancel an in-flight response:**

```json
{
  "type": "cancel"
}
```

Aborts the currently running agent response for the active session. The server sends a `cancelled` frame upon successful cancellation.

**Retry with a different model:**

```json
{
  "type": "retry_with_model",
  "message": "What are the top innovations in Kenya?",
  "model": "claude-sonnet-4-5-20250929"
}
```

Re-sends a message using an alternate model. Typically used after an AUP (Acceptable Use Policy) error, where the server suggests a fallback model.

### Server --> Client Frames

All server frames are JSON objects and include a `session_id` field identifying the conversation they belong to.

**Session assignment:**

Sent on initial connection, after `new_session`, or after `switch_session`.

```json
{
  "type": "session",
  "session_id": "a1b2c3d4"
}
```

**Streamed text:**

Sent as the agent generates its response. Content arrives as incremental chunks.

```json
{
  "type": "text",
  "content": "Based on the PRMS database, Kenya has 1,520 reported results...",
  "session_id": "a1b2c3d4"
}
```

**Extended thinking:**

Visible reasoning from the model (when extended thinking is enabled).

```json
{
  "type": "thinking",
  "content": "I need to query the PRMS database for Kenya-specific innovations...",
  "session_id": "a1b2c3d4"
}
```

**Tool invocation:**

Sent when the agent calls a tool. The frontend can display the tool name and input while waiting for the result.

```json
{
  "type": "tool_use",
  "tool": "prms_query",
  "input": {
    "query": "SELECT ri.title FROM results_innovations_dev ri JOIN result_country rc ON ri.result_id = rc.result_id WHERE rc.country_id = 114 AND ri.is_active = 1 LIMIT 20",
    "question": "What are the top innovations in Kenya?"
  },
  "tool_use_id": "toolu_01ABC123",
  "session_id": "a1b2c3d4"
}
```

**Tool result:**

Sent when a tool returns its output.

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01ABC123",
  "content": "[{\"title\": \"Drought-tolerant maize varieties\"}, {\"title\": \"Digital soil mapping toolkit\"}]",
  "is_error": false,
  "session_id": "a1b2c3d4"
}
```

**System notification:**

Informational messages about session state, agent delegation, or internal events.

```json
{
  "type": "system",
  "subtype": "init",
  "data": "Session initialized with PRMS Data Analyst",
  "session_id": "a1b2c3d4"
}
```

Common `subtype` values: `"init"`, `"agent_activity"`, `"session_resumed"`.

**Turn result:**

Sent when the agent completes its response for a given user message.

```json
{
  "type": "result",
  "estimated_cost": 0.05,
  "turns": 3,
  "duration_ms": 12000,
  "is_error": false,
  "error_detail": "",
  "session_id": "a1b2c3d4"
}
```

| Field            | Type    | Description                                    |
|------------------|---------|------------------------------------------------|
| `estimated_cost` | float   | Estimated API cost in USD for this turn         |
| `turns`          | integer | Number of agent turns (tool use cycles)         |
| `duration_ms`    | integer | Total processing time in milliseconds           |
| `is_error`       | boolean | Whether the turn ended in an error              |
| `error_detail`   | string  | Error description (empty on success)            |

**Cancellation confirmed:**

```json
{
  "type": "cancelled",
  "session_id": "a1b2c3d4"
}
```

**Error:**

```json
{
  "type": "error",
  "message": "PRMS database unavailable",
  "session_id": "a1b2c3d4"
}
```

### Session Management Flow

1. **Connect** -- The WebSocket upgrade succeeds. The server assigns the most recent session (or creates a new one) and sends a `session` frame.

2. **Send message** -- The client sends a `{"message": "..."}` frame. The server creates an SDK client for the session if needed, then streams `text`, `thinking`, `tool_use`, `tool_result`, and `system` frames. The sequence concludes with a `result` frame.

3. **New session** -- The client sends `{"type": "new_session"}`. The server creates a fresh session and responds with a `session` frame. The previous session's client remains in memory.

4. **Switch session** -- The client sends `{"type": "switch_session", "session_id": "..."}`. The server loads the target session's client (creating one with context resume if needed) and responds with a `session` frame. If the target session has an in-progress agent task, the connection attaches to its event stream and replays buffered events bracketed by `buffer_replay_start` and `buffer_replay_end` frames.

5. **Disconnect** -- In-memory clients stay alive. Reconnecting and switching back to a session resumes it with full conversation context. The `claude_session_id` (SDK internal UUID) is persisted to SQLite for context restoration after server restart.

6. **Cleanup** -- Sessions with no connected WebSocket viewers and no active tasks are periodically cleaned up to prevent orphaned CLI subprocesses.

### Error Handling

**AUP/policy error:**

When the agent's response triggers Anthropic's content policy, the server sends a specialized frame with a suggested fallback model:

```json
{
  "type": "aup_error",
  "message": "Unable to respond due to usage policy restrictions.",
  "fallback_model": "claude-sonnet-4-5-20250929",
  "session_id": "a1b2c3d4"
}
```

The client can retry by sending a `retry_with_model` frame.

**Context window exhaustion:**

When a conversation exceeds the model's context window, the `result` frame indicates the error:

```json
{
  "type": "result",
  "is_error": true,
  "error_detail": "This conversation has become too long for the model's context window. Please start a new chat to continue. Your history is preserved and can be reviewed in this session.",
  "session_id": "a1b2c3d4"
}
```

**Connection error:**

If the SDK subprocess connection is lost and automatic recovery fails:

```json
{
  "type": "error",
  "message": "Session disconnected and could not reconnect automatically. Please reload the page to continue. Your conversation history is preserved.",
  "session_id": "a1b2c3d4"
}
```

**Invalid JSON:**

Malformed client frames are rejected without terminating the WebSocket connection:

```json
{
  "type": "error",
  "message": "Invalid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
  "session_id": "a1b2c3d4"
}
```

---

## 5. OpenAPI / Swagger

Interactive API documentation is available at the live deployment:

| Interface  | URL                                                                                   |
|------------|---------------------------------------------------------------------------------------|
| Swagger UI | `https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/docs`                |
| ReDoc      | `https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/redoc`               |
| OpenAPI JSON | `https://cgiar-ia-dev-1903003658.eu-central-1.elb.amazonaws.com/openapi.json`      |

Swagger UI provides a "Try it out" feature for testing endpoints directly in the browser. All request/response schemas are auto-generated from Pydantic models.

---

## 6. Rate Limits and Quotas

Rate limiting is **not yet implemented** on the platform. The following constraints are planned for production deployment:

**Current application-level constraints:**

| Constraint                         | Value                   |
|------------------------------------|-------------------------|
| Max message length (POST /api/query) | 50,000 characters     |
| Max agent turns per session        | 200 (env: `SYNAPSIS_MAX_TURNS`) |
| Tool result truncation             | 8,000 characters        |
| WebSocket max frame size           | 1,000,000 bytes (1 MB)  |
| PRMS dashboard cache TTL           | 300 seconds (5 minutes) |
| Max concurrent in-memory sessions  | 10 (env: `SYNAPSIS_MAX_SESSIONS`) |
| Session creation rate limit        | 5 new sessions per 60-second window |

**Planned for production:**

- Per-user request rate limiting via API Gateway or Cognito-integrated middleware.
- Per-user concurrent session caps.
- Monthly query quotas tied to organizational accounts.
- Cost tracking and alerting per user/organization.
