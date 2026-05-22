# Synapsis Analytics Agent — Architecture Guide

> How the system works end-to-end: from user input to agent response, from memory to workflows, from local Docker to AWS at scale.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Request Flow: What Happens When You Send a Message](#2-request-flow)
3. [Agent Orchestration](#3-agent-orchestration)
4. [Persistent Memory System](#4-persistent-memory-system)
5. [Session Management & Resumption](#5-session-management--resumption)
6. [Workflow Pipelines](#6-workflow-pipelines)
7. [Computer Use / Desktop Automation](#7-computer-use--desktop-automation)
8. [Safety & Audit System](#8-safety--audit-system)
9. [Frontend Architecture](#9-frontend-architecture)
10. [Database Schema](#10-database-schema)
11. [Configuration System](#11-configuration-system)
12. [Deployment Architectures](#12-deployment-architectures)
13. [Extending the System](#13-extending-the-system)
14. [Key Design Decisions](#14-key-design-decisions)

---

## 1. System Overview

Synapsis is a **multi-agent analytics platform** powered by Claude via the Claude Agent SDK. It consists of:

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React SPA)              │
│  Dashboard │ Chat │ Agents │ Workflows │ Files │ ⚙️  │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + WebSocket
┌──────────────────────┴──────────────────────────────┐
│                  FastAPI Backend                     │
│  ┌─────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ REST API│  │WebSocket │  │ SPA Catch-all     │  │
│  │ /api/*  │  │ /ws/*    │  │ /* → index.html   │  │
│  └────┬────┘  └────┬─────┘  └───────────────────┘  │
│       │             │                                │
│  ┌────┴─────────────┴────────────────────────────┐  │
│  │           Claude Agent SDK                     │  │
│  │  ┌──────────────────────────────────────────┐ │  │
│  │  │  Main Orchestrator (Opus 4.6)            │ │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌────────────┐ │ │  │
│  │  │  │ Task    │ │ Memory  │ │ Computer   │ │ │  │
│  │  │  │ (route) │ │ (MCP)   │ │ (MCP)      │ │ │  │
│  │  │  └────┬────┘ └─────────┘ └────────────┘ │ │  │
│  │  │       │ delegates to                     │ │  │
│  │  │  ┌────┴────────────────────────────────┐ │ │  │
│  │  │  │ 5 Specialist SubAgents (Opus)        │ │ │  │
│  │  │  │ data │ viz │ research │ code │ gui  │ │ │  │
│  │  │  └─────────────────────────────────────┘ │ │  │
│  │  └──────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────┐  ┌───────────────┐  ┌──────────┐      │
│  │ SQLite   │  │ SQLite        │  │ Audit    │      │
│  │ chat.db  │  │ wf_runs.db   │  │ Log      │      │
│  └──────────┘  └───────────────┘  └──────────┘      │
│  ┌──────────────────────────────────────────────┐   │
│  │ Safety Hooks (pre-tool) + Run Managers       │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

**Key principle:** The frontend is purely a presentation layer. Every capability is accessible via REST API and WebSocket directly. You could replace the React app with curl, a Python script, a Slack bot, or a mobile app without changing any backend code.

### Backend package structure (`synapsis/`)

The backend is organized as a Python package with focused sub-packages:

```
synapsis/
├── __init__.py             # Package metadata
├── config.py               # All env vars, paths, logging, auth detection
├── constants.py            # Centralized magic values, app-wide settings
├── models.py               # Pydantic request/response models
├── system_prompt.py        # Orchestrator system prompt builder
├── agent_options.py        # ClaudeAgentOptions builder
├── server.py               # FastAPI assembly, startup, static mount
├── websocket.py            # /ws/chat streaming handler
├── workflow_ws.py          # /ws/workflow/{id} pipeline execution
├── ws_utils.py             # Shared WebSocket utilities
├── stream_handler.py       # Consumes Claude SDK async generator
├── stream_core.py          # Shared streaming utilities (chat + workflow)
├── stream_callbacks.py     # StreamCallbacks DI container
├── message_handlers.py     # Message block processing
├── chat_run_manager.py     # Chat task lifecycle (WS-independent)
├── workflow_run_manager.py # Concurrent pipeline execution manager
├── run_manager_utils.py    # Shared attach/detach/cancel patterns
├── session_manager.py      # Backward-compatible re-export shim
├── db_manager.py           # DB connection management
├── workflow_db.py          # Workflow DB re-export shim
├── agents/                 # Subagent definitions and loading
│   ├── definitions.py      # 5 AgentDefinition (default opus)
│   ├── registry.py         # AGENT_REGISTRY + display metadata
│   └── loader.py           # Merges builtin + DB custom agents
├── database/               # SQLite persistence layer
│   ├── connection.py, schema.py, messages.py, sessions.py, memory.py, tasks.py
│   └── workflow_*.py       # Workflow runs DB (connection, schema, runs, steps, messages)
├── tools/                  # MCP server tools (synapsis: 7, computer-use: 11)
│   ├── memory.py           # 4 memory tools
│   ├── agents.py           # 3 agent management tools
│   ├── slack.py            # Slack notification tool
│   ├── computer_use_server.py  # macOS: 11 computer-use tools (screenshot, click, type, key, scroll, etc.)
│   ├── coordinate_scaling.py   # Display detection and API constraint math
│   └── macos_input.py          # CGEvent key delivery and scroll via PyObjC
├── hooks/                  # Safety + audit hooks
│   ├── safety.py           # Pre-tool command blocking
│   └── audit.py            # Post-tool audit logging
├── routes/                 # REST API (15 route modules)
│   ├── health.py, files.py, sessions.py, memories.py, query.py
│   ├── export.py, search.py, agents.py, dashboard.py
│   ├── workflows.py, workflow_runs.py, workflow_logs.py
│   ├── transcribe.py, git.py
│   └── __init__.py
├── services/               # Business logic (9 modules)
│   ├── agent_service.py, search_service.py, session_service.py
│   ├── workflow_service.py, workflow_executor.py, workflow_step_runner.py
│   ├── workflow_step_helpers.py, workflow_persistence.py
│   └── workflow_stream_handler.py
├── handlers/               # WebSocket message handlers
│   ├── chat_handlers.py, utils.py
├── session/                # Session management package
│   ├── manager.py, client_registry.py, client_factory.py
│   ├── connection_registry.py, broadcast.py, cancel.py
├── exporters/              # Format exporters
│   ├── markdown.py, html.py, docx.py, workflow_run.py
│   ├── common.py, message_visitor.py
├── utils/                  # Shared helpers
│   ├── db_helpers.py, responses.py
└── validators/             # Input validation
    └── agents.py
```

**Key design principles:**
- Each module targets <300 lines -- easy for AI/LLM agents to read in full
- Single responsibility -- each file does one thing
- Config centralized -- all env vars in `config.py`, imported by other modules
- Sub-packages group related modules (database/, tools/, hooks/, routes/, services/, session/, exporters/)
- Import direction: config -> database/tools/hooks/agents -> agent_options -> routes/websocket -> server -> app.py

---

## 2. Request Flow

### What happens when you type a message and press Enter:

```
1. User types "Analyze my sales data" → ChatInput component
   │
2. ChatInput calls send({type: "message", message: "..."})
   │
3. WebSocket sends JSON frame to /ws/chat
   │
4. websocket.py receives message
   │  ├─ If no session exists: create new session (8-char UUID)
   │  ├─ If no SDK client exists: create ClaudeSDKClient with build_agent_options()
   │  │   └─ Injects: system prompt, 5 subagents, memory MCP, computer MCP, hooks
   │  └─ Save user message to SQLite (messages table)
   │
5. client.query("Analyze my sales data") → async generator
   │
6. stream_handler.py processes each event:
   │
   │  StreamEvent (real-time deltas)
   │  ├─ text_delta → buffer text → send {"type": "text", "content": "..."} to WebSocket
   │  └─ thinking_delta → buffer thinking → send {"type": "thinking", "content": "..."}
   │
   │  AssistantMessage (complete blocks)
   │  ├─ TextBlock → finalize text buffer → save to DB
   │  ├─ ThinkingBlock → finalize thinking buffer → save to DB
   │  ├─ ToolUseBlock → send {"type": "tool_use", ...} → save to DB
   │  │   └─ If tool is "Task" → send {"type": "agent_activity", "agent": "data_analysis"}
   │  └─ ToolResultBlock → send {"type": "tool_result", ...} → save to DB
   │
   │  ResultMessage (turn complete)
   │  └─ send {"type": "result", "estimated_cost": ..., "turns": ..., "duration_ms": ...}
   │
7. Frontend receives streamed events:
   │  ├─ chat.ts store accumulates text/thinking in buffers
   │  ├─ MessageList renders finalized messages
   │  ├─ StreamingMessage renders live text with blinking cursor
   │  ├─ ToolCallCard shows tool invocations with expand/collapse
   │  └─ AgentActivityBanner shows "Data Analysis is working..."
   │
8. Turn completes → ResultBanner shows cost + duration + turns
```

### Hook execution during tool calls:

```
Agent decides to call Bash("python analyze.py")
   │
   ├─ PreToolUse: safety_validator checks command against dangerous patterns
   │   └─ If match (rm -rf /, fork bomb, etc.) → DENY with reason → agent sees error
   │
   ├─ PreToolUse: audit_logger writes to audit.log:
   │   "[2026-03-28T14:30:00] PreToolUse tool=Bash input={command: python analyze.py}"
   │
   ├─ Tool executes: Bash runs "python analyze.py"
   │
   └─ PostToolUse: audit_logger_post writes to audit.log:
       "[2026-03-28T14:30:05] PostToolUse tool=Bash result={output truncated to 300 chars}"
```

---

## 3. Agent Orchestration

### The Two-Tier Model

**Tier 1 — Main Orchestrator (Claude Opus 4.6):**
- Reads the user's query
- Decides which specialist to delegate to (or handles it directly)
- Uses the `Task` tool to invoke subagents
- Synthesizes subagent results into a coherent response
- Manages memory (store, recall, list, forget)
- Has access to ALL tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, TodoWrite, Task, plus all MCP tools

**Tier 2 — Specialist SubAgents (5 × Claude Opus):**

| Agent | Role | Unique Tools |
|-------|------|-------------|
| `data_analysis` | Statistical analysis, EDA, regression, data wrangling | Standard file + web tools |
| `visualization_reporting` | Charts, dashboards, reports (HTML/PDF/DOCX) | Standard file + web tools |
| `research_methodology` | Study design, power analysis, sampling strategies | Standard file + web tools |
| `code_automation` | ETL pipelines, scraping, API integration, scripting | Standard file + web tools |
| `computer_use` | GUI interaction, browser control, screenshots | Bash + 11 `mcp__computer-use__*` tools |

### How routing works:

The orchestrator doesn't use if/else routing. Instead, its system prompt describes each subagent's specialization, and the orchestrator makes intelligent delegation decisions via the `Task` tool:

```
User: "Create a scatter plot of height vs weight from data.csv"

Orchestrator thinks: "This involves data visualization → delegate to visualization_reporting"

Orchestrator calls: Task(agent="visualization_reporting", prompt="Create a scatter plot...")

visualization_reporting agent:
  1. Reads data.csv
  2. Writes Python script with matplotlib
  3. Runs the script via Bash
  4. Returns the result

Orchestrator receives the result and presents it to the user.
```

For complex queries, the orchestrator may invoke **multiple agents** sequentially:

```
User: "Design a study, determine sample size, then create a data collection template"

Orchestrator:
  1. Task(agent="research_methodology", prompt="Design the study...")
  2. Task(agent="research_methodology", prompt="Calculate sample size for...")
  3. Task(agent="code_automation", prompt="Create a data collection spreadsheet...")
  4. Synthesizes all results
```

### SubAgent definition structure:

Each subagent is defined in `synapsis/agents/definitions.py` as an `AgentDefinition`:

```python
"data_analysis": AgentDefinition(
    description="Statistical analysis, EDA, hypothesis testing...",
    prompt="You are the Data Analysis specialist...",  # Full system prompt
    tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
    model="opus",
)
```

All subagents default to `model="opus"`. The `computer_use` agent is special — it gets `Bash` plus all 11 `mcp__computer-use__*` tools (from the dedicated `computer-use` MCP server), and its system prompt dynamically adapts to the platform (macOS apps vs. Linux apps, Cmd vs. Ctrl shortcuts).

---

## 4. Persistent Memory System

### How memories work:

Memories are key-value pairs stored in SQLite with full-text search (FTS5). They persist across sessions and allow the agent to remember context about the user, their projects, and past decisions.

```
┌──────────────────────────────────────────┐
│            Memory Lifecycle              │
│                                          │
│  1. Agent encounters important info      │
│     "The user prefers R over Python"     │
│                                          │
│  2. Agent calls memory_store():          │
│     category: "user_profile"             │
│     content: "Prefers R over Python"     │
│     importance: 7                        │
│     tags: "preferences, language"        │
│                                          │
│  3. Stored in SQLite memories table      │
│     + FTS5 index updated                 │
│     + Duplicate detection (update if     │
│       same category + content exists)    │
│                                          │
│  4. Next session starts:                 │
│     Top 20 memories by importance        │
│     injected into agent's context        │
│                                          │
│  5. Agent can also actively search:      │
│     memory_recall("language preference") │
│     → Returns matching memories          │
│     → Bumps access_count                 │
│                                          │
│  6. Agent can forget:                    │
│     memory_forget(id=42)                 │
│     → Soft-delete (active=0)             │
│     → Preserved for audit trail          │
└──────────────────────────────────────────┘
```

### Memory categories:

| Category | When to use | Example |
|----------|-------------|---------|
| `user_profile` | User preferences, background | "Prefers R, works in healthcare" |
| `project_context` | Project-specific parameters | "Dataset has 50K rows, quarterly data since 2020" |
| `analysis_decision` | Key choices and rationale | "Chose Mann-Whitney U because data is non-normal" |
| `methodology_note` | Reference values, formulas | "Cohen's d > 0.8 = large effect" |
| `best_practice` | General analytical guidance | "Always check VIF for multicollinearity" |
| `escalation_record` | Handoff records | "Referred to statistician for Bayesian hierarchical model" |

### Seed knowledge:

On first run, `seed_knowledge.py` pre-loads foundational memories:
- Statistical test selection guide
- Effect size interpretation tables (Cohen's conventions)
- Sample size rules of thumb
- Data quality checklist
- Visualization best practices

These give the agent immediate reference knowledge without requiring the user to teach it.

---

## 5. Session Management & Resumption

### Session lifecycle:

```
New Session
  │
  ├─ Generate 8-char UUID (e.g., "a1b2c3d4")
  ├─ Create DB entry in sessions table
  ├─ Create ClaudeSDKClient with agent options
  ├─ Store client in sessions dict: sessions["a1b2c3d4"] = client
  │
  ▼
Active Session
  │
  ├─ User sends messages → client.query() → stream response
  ├─ All messages saved to DB (messages table)
  ├─ SDK's internal session UUID saved: claude_session_id → DB
  │
  ▼
Session Switch (user clicks different session)
  │
  ├─ Load target session's client from sessions dict
  │   OR create new client with resume_session_id from DB
  ├─ Load message history from DB → send to frontend
  │
  ▼
Disconnect (browser closed)
  │
  ├─ Client stays alive in sessions dict (in-memory)
  ├─ WebSocket cleanup: remove from active connections
  │
  ▼
Reconnect
  │
  ├─ Frontend sends {"type": "switch_session", "session_id": "a1b2c3d4"}
  ├─ Server reuses existing client from sessions dict
  ├─ If client was garbage collected: creates new client with
  │   resume_session_id = claude_session_id from DB
  ├─ SDK resumes the conversation context
  │
  ▼
Server Restart
  │
  ├─ All in-memory clients are lost
  ├─ DB has session records + claude_session_id
  ├─ On next connect: new client created with resume_session_id
  └─ SDK restores context from its server-side session state
```

### Key implementation detail:

The system maintains **two session IDs**:
1. **App session ID** (8-char UUID) — generated by Synapsis, used as the primary key
2. **Claude session ID** (full UUID) — the SDK's internal session identifier, used for context resumption

The mapping between them is stored in the `sessions.claude_session_id` column.

### Multi-session streaming & concurrency

The app supports multiple sessions streaming simultaneously. A single WebSocket connection carries messages for ALL sessions, tagged with `session_id`. This creates subtle routing challenges:

#### Frontend message routing (`useWebSocket.ts`)

```
Incoming WebSocket message
  │
  ├─ Session management (session, sessions_changed, session_update, session_complete)
  │   → Always processed, regardless of session_id
  │
  ├─ Active session match (msgSession === activeSession)
  │   → Processed into chat store via handleServerMessage()
  │
  ├─ No active session (activeSession is null, e.g. "New Chat" clicked)
  │   → Messages WITH a session_id → background handling (NOT into chat store)
  │   → Messages WITHOUT a session_id → processed (backward compat)
  │   ⚠️ Using `!activeSession` as a pass-through causes token leakage into new chats
  │
  └─ Background session (msgSession !== activeSession)
      ├─ text/thinking → append to _sessionCache (preserves streaming content)
      ├─ tool_use/tool_result → invalidate cache (structural change)
      └─ result/cancelled/error → invalidate cache + mark session complete
```

#### Frontend session cache (`stores/chat.ts`)

When switching away from a session, the frontend snapshots the current chat state (messages, streaming buffers, busy state) into `_sessionCache`. When switching back, it restores from cache for instant display. This is critical for seamless multi-session switching:

```
Session A streaming → User clicks Session B
  │
  ├─ cacheCurrentSession(A)  — snapshot A's state (messages + streamingText)
  ├─ Load Session B (from cache or DB)
  │
  │  While viewing B, tokens for A arrive via WebSocket:
  │  ├─ text/thinking → appendToCachedStream(A, ...)  — accumulates in cache
  │  ├─ tool_use → invalidateCachedSession(A) — cache too stale
  │  └─ result → invalidateCachedSession(A) + markComplete
  │
  └─ User clicks Session A again
      ├─ cacheCurrentSession(B) — snapshot B
      ├─ restoreSession(A)?
      │   ├─ Cache exists → restore instantly (with accumulated tokens) ✓
      │   └─ Cache invalidated → loadHistory(A) from DB ✓
      └─ New tokens continue streaming normally
```

**Critical invariant:** Both `handleNewChat()` AND `handleSelect()` in `SessionList.tsx` must call `cacheCurrentSession()` before switching away. Missing this causes background tokens to have nowhere to accumulate, resulting in lost content.

#### Streaming buffer finalization (`stores/chat.ts`)

The store accumulates text/thinking tokens in `streamingText`/`streamingThinking` buffers. These are flushed into permanent `messages[]` entries by `finalizeText()`/`finalizeThinking()`:

- **Triggered by**: structural events (`tool_use`, `result`, `cancelled`, `session_complete`)
- **NOT triggered by**: timers or token count thresholds
- **Must be called before**: `clearMessages()`, `loadHistory()`, `addUserMessage()`, or any operation that replaces/clears the buffers

Forgetting to finalize before clearing = **silently destroyed content**.

#### Backend per-session locking (`session_manager.py`)

Multiple WebSocket connections (browser tabs, devices) can view the same session. Per-session `asyncio.Lock` prevents concurrent `client.query()` calls:

```
Device 1 sends message to Session A
  │
  ├─ acquire_session_client(A) — acquires lock
  ├─ client.query(message) → stream_response() starts
  │
  │  Device 2 sends message to Session A
  │  ├─ acquire_session_client(A) — blocks until Device 1's stream finishes
  │  └─ (or creates parallel client with resume_session_id if configured)
  │
  └─ stream_response() finally block → on_complete() → release_session_client(A)
```

#### Cross-device broadcasting (`session_manager.py`)

A connection registry (`_all_connections`, `_connection_registry`) tracks which WebSocket connections are viewing which sessions:

- `broadcast_to_all({"type": "sessions_changed"})` — notifies all devices to refresh session list (used after rename, new message)
- `broadcast_to_session(sid, data)` — notifies only viewers of a specific session
- `broadcast_to_all({"type": "session_update", "action": "deleted", "session_id": sid})` — notifies all devices about session deletion

---

## 6. Workflow Pipelines

### What workflows are:

A workflow chains multiple specialist agents into a sequential pipeline. Each agent receives the output of the previous agent as its input.

```
┌──────────┐     ┌──────────────┐     ┌───────────────┐
│   User   │     │ Data         │     │ Visualization │
│  Prompt  │────▶│ Analysis     │────▶│ & Reporting   │
│          │     │ (Opus)       │     │ (Opus)        │
└──────────┘     └──────────────┘     └───────────────┘
                  Output: "Found                Output: "Created
                  3 trends..."                  bar chart at..."
```

### Execution model:

1. User creates a workflow via `POST /api/workflows` with an `agentSequence`
2. User triggers execution via WebSocket `/ws/workflow/{id}`
3. For each agent in the sequence:
   - A **fresh SDK client** is created with that agent's system prompt
   - First step receives the user's initial prompt
   - Subsequent steps receive: `"Previous agent ({name}) produced:\n\n{output}\n\nNow continue..."`
   - All events are streamed to the frontend via WebSocket
   - Output is accumulated for the next step
4. Pipeline completes when all steps finish

### Why fresh clients per step:

Each pipeline step creates a new `ClaudeSDKClient` with the target agent's system prompt overriding the default. This prevents **personality contamination** — the visualization agent doesn't carry context from the data analysis agent's system prompt. Each agent behaves authentically within its role.

### Common pipeline patterns:

| Pattern | Agents | Use case |
|---------|--------|----------|
| Data → Viz | data_analysis → visualization_reporting | Analyze data, then create charts |
| Research → Analysis → Report | research_methodology → data_analysis → visualization_reporting | Full research cycle |
| Scrape → Analyze | code_automation → data_analysis | Collect data, then analyze |
| Full Pipeline | code_automation → data_analysis → visualization_reporting | End-to-end |

---

## 7. Computer Use / Desktop Automation

### Architecture: Two MCP servers

Desktop automation is split across two MCP servers:

1. **`synapsis`** — Memory, agent management, and Slack tools (7 tools)
2. **`computer-use`** — All 11 desktop interaction tools

The `computer_use` subagent gets `Bash` plus the full `computer-use` MCP server. The orchestrator and other subagents do not have access to desktop tools.

### The `computer-use` MCP server (11 tools)

| Tool | Description |
|------|-------------|
| `mcp__computer-use__screenshot` | Capture screen, pre-resize to API constraints |
| `mcp__computer-use__left_click` | Left-click at (x, y) |
| `mcp__computer-use__right_click` | Right-click at (x, y) |
| `mcp__computer-use__double_click` | Double-click at (x, y) |
| `mcp__computer-use__middle_click` | Middle-click at (x, y) |
| `mcp__computer-use__mouse_move` | Move cursor to (x, y) |
| `mcp__computer-use__left_click_drag` | Click-drag from (x1, y1) to (x2, y2) |
| `mcp__computer-use__type` | Type text string |
| `mcp__computer-use__key` | Press key combination |
| `mcp__computer-use__scroll` | Scroll at (x, y) by delta |
| `mcp__computer-use__cursor_position` | Report current cursor position |

### Platform implementations:

| Subsystem | macOS | Linux |
|-----------|-------|-------|
| **Screenshots** | `screencapture -x` | `xwd` + ImageMagick `import` |
| **Mouse clicks** | `cliclick` (`m:x,y c:.`, `rc:.`, `dc:.`) | `xdotool mousemove x y click N` |
| **Key delivery** | CGEvent via PyObjC (`macos_input.py`) | `xdotool key` |
| **Scroll** | CGEvent scroll wheel via PyObjC | `xdotool click --repeat N 4/5` |
| **Text input** | CGEvent key-by-key delivery | `xdotool type --delay 10` |

### Coordinate scaling (`coordinate_scaling.py`):

Screenshots are pre-resized before being sent to the API to stay within Anthropic's constraints (1568px longest edge, ~1.15 megapixels). Coordinates returned by the model are in the resized image space and must be mapped back to actual screen coordinates before dispatching clicks.

```
Actual display (e.g., 2560×1600)
  │
  ├─ screencapture → actual pixel PNG
  │   └─ Measure actual output dimensions (not NSScreen.mainScreen().frame())
  │
  ├─ Resize to fit API constraints → scaled PNG (e.g., 1568×980)
  │   └─ Send to Claude as base64 image
  │
  └─ Model returns click at (x_scaled, y_scaled)
      └─ Map back: x_actual = x_scaled × (actual_w / scaled_w)
                   y_actual = y_scaled × (actual_h / scaled_h)
```

**Display detection:** The system measures the actual `screencapture` output dimensions rather than relying on `NSScreen.mainScreen().frame()`, which reports logical points (not pixels) and is inaccurate on Retina displays or non-default resolutions.

### App launchers (built into the agent's system prompt):

**macOS:** Safari, Chrome, Preview, TextEdit, Numbers, Pages, Finder, Terminal

**Linux:** Firefox, Chromium, LibreOffice Writer/Calc, Atril, Ristretto, Mousepad, Thunar, XFCE Terminal

### Desktop viewing:

- **Linux (Docker):** Desktop runs in Xvfb + XFCE4 with x11vnc, accessible via noVNC in the browser
- **macOS (native):** No VNC — the agent controls the real desktop directly. The frontend hides the desktop viewer panel.

---

## 8. Safety & Audit System

### Three layers of safety:

```
Layer 1: System Prompt Scope Boundaries
  │  Agent refuses out-of-scope requests politely
  │  ("I'm designed for data analysis, not...")
  │
Layer 2: PreToolUse Safety Hook
  │  Blocks dangerous Bash commands before execution
  │  Patterns: rm -rf /, mkfs, dd if=, fork bombs,
  │  chmod -R 777 /, DROP DATABASE, DROP TABLE
  │
Layer 3: Audit Logging
     Records ALL tool invocations to disk
     Pre-tool: timestamp, tool name, input (500 chars)
     Post-tool: timestamp, tool name, output (300 chars)
     Path: {WORKSPACE}/.synapsis/audit.log
```

### Safety hook behavior:

- **Enabled by default on Linux** (Docker containers — shared infrastructure)
- **Disabled by default on macOS** (dedicated agent machine assumption)
- Configurable via `SYNAPSIS_SAFETY_HOOKS` env var

When a dangerous command is blocked:
```
Agent tries: Bash("rm -rf /")
  │
  └─ safety_validator matches pattern → returns:
     {
       permissionDecision: "deny",
       permissionDecisionReason: "Blocked: rm\\s+-rf\\s+/\\s"
     }

     Agent sees: "Permission denied: Blocked dangerous command pattern"
     Agent tells user: "I can't run that command because..."
```

### Audit log format:

```
[2026-03-28T14:30:00.123] PreToolUse tool=Bash input={"command": "python analyze.py"}
[2026-03-28T14:30:05.456] PostToolUse tool=Bash result={"output": "Analysis complete..."}
[2026-03-28T14:30:05.789] PreToolUse tool=Write input={"file_path": "/workspace/results.csv", "content": "..."}
[2026-03-28T14:30:05.890] PostToolUse tool=Write result={"success": true}
```

Hooks write **immediately** (before tool execution completes) so that even failed tool calls leave a trail.

---

## 9. Frontend Architecture

### Multi-page SPA with React Router:

```
BrowserRouter
  └─ Routes
       └─ Layout (TopBar + Outlet + Toast)
            ├─ / → Dashboard
            ├─ /chat → Chat (Sidebar + ChatArea + DesktopViewer)
            ├─ /agents → Agents (grid + detail modal)
            ├─ /workflows → Workflows (React Flow + PipelineRunner)
            ├─ /files → Files (browser + upload)
            └─ /settings → Settings (theme + config)
```

### State management (Zustand):

| Store | Contents | Persisted? |
|-------|----------|-----------|
| `chat.ts` | Messages, streaming buffers, busy state, active agent, AUP errors | No (ephemeral) |
| `sessions.ts` | Session list, active session ID, busy sessions | No (fetched from API) |
| `ui.ts` | Theme, sidebar state, desktop panel state | Theme → localStorage |

### Data fetching pattern:

The `useApi<T>(fetcher, fallback)` hook provides **graceful degradation**:

```typescript
const { data, loading, error, isLive, refetch } = useApi<DashboardStats>(
  () => dashboardService.getStats(),   // Real data fetcher
  mockDashboardStats,                   // Fallback if API fails
  { interval: 30000 }                  // Poll every 30s
);
```

If the backend is down, the UI shows mock data instead of blank screens or error states. The `isLive` flag indicates whether data is real or fallback.

### WebSocket streaming architecture:

```
WebSocket /ws/chat
  │
  └─ useWebSocket hook
       ├─ Automatic reconnection (exponential backoff: 1s → 30s)
       ├─ Session-aware: filters messages by active session
       ├─ Routes events → chat.ts store via handleServerMessage()
       │
       └─ handleServerMessage() switch:
            ├─ "text" → append to streamingText buffer
            ├─ "thinking" → append to streamingThinking buffer
            ├─ "tool_use" → finalize buffers → add tool_use message
            ├─ "tool_result" → add tool_result message
            ├─ "agent_activity" → set activeAgent state
            ├─ "result" → finalize all buffers → add result message
            ├─ "session" → update active session
            ├─ "aup_error" → set aupError state → show retry UI
            ├─ "cancelled" → clear busy state
            └─ "error" → show error toast
```

### Navigation:

- **TopBar:** Animated navigation pills using framer-motion `layoutId` for smooth transitions
- **Command Palette:** `Cmd+K` opens search, `Cmd+1` through `Cmd+6` for direct page navigation
- **Keyboard shortcuts:** Arrow keys + Enter in command palette

---

## 10. Database Schema

The primary data store is a SQLite file at `{WORKSPACE}/.synapsis/chat.db`. A second SQLite database at `{WORKSPACE}/.synapsis/workflow_runs.db` stores workflow execution history (see [Workflow Runs](#workflow-runs-database) below).

### Tables:

```sql
-- Chat messages (all types: user, text, thinking, tool_use, tool_result, system, result)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts REAL NOT NULL,           -- Unix timestamp
    type TEXT NOT NULL,          -- Message type
    data TEXT NOT NULL           -- JSON-serialized content
);
CREATE INDEX idx_messages_session ON messages(session_id, ts);

-- Chat sessions
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY, -- 8-char UUID prefix
    title TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    model TEXT DEFAULT '',
    message_count INTEGER DEFAULT 0,
    claude_session_id TEXT DEFAULT '',  -- SDK session UUID for resumption
    pinned INTEGER DEFAULT 0
);

-- Persistent memories with full-text search
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 5,       -- 1-10
    source_session TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    access_count INTEGER DEFAULT 0,     -- Bumped on each recall
    tags TEXT DEFAULT '',
    active INTEGER DEFAULT 1            -- 0 = soft-deleted
);
CREATE INDEX idx_memories_category ON memories(category, active);
CREATE INDEX idx_memories_importance ON memories(importance DESC, active);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, tags,
    content='memories',
    content_rowid='id'
);

-- Multi-agent workflow pipelines
CREATE TABLE workflows (
    id TEXT PRIMARY KEY,            -- 8-char UUID prefix
    name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',    -- draft, running, completed, failed, cancelled
    progress INTEGER DEFAULT 0,     -- 0-100
    steps INTEGER DEFAULT 0,
    agent_sequence TEXT DEFAULT '[]', -- JSON array of agent IDs
    initial_prompt TEXT DEFAULT '',
    nodes TEXT DEFAULT '[]',         -- React Flow visual state
    edges TEXT DEFAULT '[]',
    created_at REAL,
    updated_at REAL,
    run_count INTEGER DEFAULT 0,
    last_run REAL
);
```

### Migration system:

On startup, `init_db()` runs schema migrations to add new columns to existing databases:
- `claude_session_id` column on sessions (for session resumption)
- `pinned` column on sessions (for starring)

This allows zero-downtime upgrades without data loss.

### Workflow Runs Database

A second SQLite database at `{WORKSPACE}/.synapsis/workflow_runs.db` stores workflow execution history, managed by `synapsis/workflow_db.py` and the `synapsis/database/workflow_*.py` modules:

```sql
-- Individual pipeline executions
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT,
    status TEXT DEFAULT 'running',  -- running, completed, failed, cancelled
    agent_sequence TEXT,            -- JSON array of agent IDs
    started_at REAL,
    completed_at REAL,
    log_filename TEXT               -- Path to on-disk JSON log (richest data)
);

-- Steps within a run (one per agent in the sequence)
CREATE TABLE workflow_run_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    agent_id TEXT,
    status TEXT DEFAULT 'pending',
    started_at REAL,
    completed_at REAL
);

-- Messages generated during each step (text, tool_use, tool_result, etc.)
CREATE TABLE workflow_run_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL,              -- JSON-serialized message content
    ts REAL NOT NULL
);
```

Keeping run history in a separate database avoids write contention with the main `chat.db` during long-running pipeline executions and keeps the primary database lean.

---

## 11. Configuration System

### Environment variables (centralized in `synapsis/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNAPSIS_MODEL` | `claude-opus-4-6` | Main orchestrator model |
| `SYNAPSIS_FALLBACK_MODEL` | `claude-sonnet-4-5-20250929` | Used for AUP retries and subagents |
| `SYNAPSIS_MAX_TURNS` | `200` | Maximum agentic iterations per session |
| `SYNAPSIS_WORKSPACE` | `~/workspace` (macOS), `/workspace` (Linux) | Working directory |
| `SYNAPSIS_HOST` | `0.0.0.0` | Server bind address |
| `SYNAPSIS_PORT` | `7777` | Server port |
| `SYNAPSIS_LOG_LEVEL` | `INFO` | Python logging level |
| `SYNAPSIS_SAFETY_HOOKS` | `false` (macOS), `true` (Linux) | Enable dangerous command blocking |
| `SYNAPSIS_PLATFORM` | Auto-detected | `"macos"` on Darwin, `"linux"` otherwise |
| `ANTHROPIC_API_KEY` | *(empty)* | Fallback auth if no Claude Code subscription |

### Platform detection:

```python
# Automatic
SYNAPSIS_PLATFORM = "macos" if sys.platform == "darwin" else "linux"
IS_MACOS = SYNAPSIS_PLATFORM == "macos"

# This boolean gates:
# - Computer tool implementation (screencapture vs xdotool)
# - Safety hook defaults (disabled vs enabled)
# - Workspace path (~/ vs /)
# - System prompt app names (Safari vs Firefox, Cmd vs Ctrl)
# - App launcher commands in computer_use agent prompt
```

### Authentication detection (checked in order):

1. `~/.claude` directory exists → `auth_method = "subscription"` (Claude Code Pro)
2. `ANTHROPIC_API_KEY` env var set → `auth_method = "api_key"`
3. Neither → `auth_method = "none"` (error logged, agent won't work)

---

## 12. Deployment Architectures

### Mode 1: Local Docker (single-user, fastest to start)

```bash
./start.sh   # Detects auth, builds image, launches docker-compose
```

```
┌─────────────────────────────────┐
│      Docker Container           │
│  ┌───────────────────────────┐  │
│  │ FastAPI + Agent SDK       │  │ Port 7777
│  │ + Xvfb + XFCE4 + VNC     │  │ Port 6081 (noVNC)
│  │ + Chromium + LibreOffice  │  │
│  └───────────────────────────┘  │
│  Volume: ~/.claude (read-only)  │
│  Volume: workspace (persistent) │
└─────────────────────────────────┘
```

### Mode 2: Native macOS (development, controls real desktop)

```bash
./start-macos.sh   # Checks prereqs, builds frontend, launches server
```

```
┌─────────────────────────────────┐
│      macOS Direct               │
│  Python → FastAPI → Agent SDK   │ Port 7777
│  screencapture + cliclick       │ (real desktop)
│  Safari, Preview, Numbers, etc. │
└─────────────────────────────────┘
```

No Docker, no VNC. The agent controls the actual macOS desktop. Ideal for a dedicated Mac Mini agent machine.

### Mode 3: AWS (multi-user, auto-scaling)

```
                    ┌───────────────┐
                    │  API Gateway  │
                    └───────┬───────┘
                            │
              ┌─────────────┼──────────────┐
              │             │              │
        ┌─────┴─────┐ ┌────┴────┐ ┌──────┴──────┐
        │ provision  │ │ status  │ │  cleanup    │
        │ Lambda     │ │ Lambda  │ │  Lambda     │
        └─────┬──────┘ └────┬────┘ │ (cron 5min) │
              │              │     └──────┬──────┘
              │         ┌────┴────────────┘
              │         │
        ┌─────┴─────────┴────────────────────┐
        │       EC2 Auto Scaling Group        │
        │  ┌─────────────────────────────┐   │
        │  │  t3.2xlarge instance        │   │
        │  │  ┌────────┐ ┌────────┐      │   │
        │  │  │Agent:0 │ │Agent:1 │ ...  │   │ × up to 7 instances
        │  │  │:7701   │ │:7702   │      │   │ × 3 containers each
        │  │  └────────┘ └────────┘      │   │ = 21 concurrent users
        │  └─────────────────────────────┘   │
        └────────────────────────────────────┘
                            │
                    ┌───────┴───────┐
                    │   DynamoDB    │
                    │ users + inst  │
                    └───────────────┘
```

**Bin-packing strategy:** Each t3.2xlarge (8 vCPU, 32GB) runs up to 3 agent containers. The provision Lambda finds the cheapest available slot before launching new instances.

**Three-layer idle shutdown:**
1. Cleanup Lambda (every 5 min) — stops containers idle > 30 min
2. UserData cron (every 15 min) — terminates instance if 0 containers running
3. Hard shutdown timer — max 8-hour instance lifetime

---

## 13. Extending the System

### Adding a new subagent:

1. **Define** in `synapsis/agents/definitions.py`:
```python
"my_new_agent": AgentDefinition(
    description="One-line description for the orchestrator",
    prompt="You are the My New Agent specialist...",
    tools=["Read", "Write", "Edit", "Bash", ...],
    model="opus",
)
```

2. **Update metadata** in `synapsis/agents/registry.py`:
```python
_AGENT_DISPLAY_META["my_new_agent"] = {
    "name": "My New Agent",
    "type": "Category",
    "avatarHue": 180,
}
```

3. **Update system prompt** in `synapsis/system_prompt.py` to mention when to use the new agent

4. The orchestrator can now route to it via the Task tool — no other changes needed.

### Adding a new MCP tool:

1. **Create tool** in `synapsis/tools/my_tool.py` with `@tool()` decorator
2. **Register** in `synapsis/tools/__init__.py` — add to `create_sdk_mcp_server(tools=[...])`
3. **Allowlist** in `synapsis/agent_options.py` — add `"mcp__synapsis__my_tool"` to `allowed_tools` (or use the `computer-use` server for desktop tools)
4. **Document** in system prompt so the agent knows when to use it

### Adding a new API endpoint:

1. **Create router** in `synapsis/routes/my_feature.py`
2. **Register** in `synapsis/routes/__init__.py` (export the router)
3. **Include** in `synapsis/server.py`: `app.include_router(my_feature_router)`

### Adding a new frontend page:

1. **Create page** in `frontend/src/pages/MyPage.tsx`
2. **Add route** in `App.tsx`: `<Route path="/mypage" element={<MyPage />} />`
3. **Add nav item** in `components/layout/TopBar.tsx` (add to `NAV_ITEMS` array)
4. **Add command** in `components/layout/CommandPalette.tsx` (add to `COMMANDS` array)

---

## 14. Key Design Decisions

### Why SQLite databases?

The system uses two SQLite databases:
1. **`chat.db`** — Sessions, messages, memories, workflows, and custom agents
2. **`workflow_runs.db`** — Workflow run history, steps, and step messages (accessed via `workflow_db.py`)

Separating workflow run history into its own database keeps the main chat database lean and avoids write contention during long-running pipeline executions.

Benefits of SQLite:
- Zero configuration — no external database server needed
- Portable — the entire state is a pair of files you can copy
- Fast enough for single-user / few-user scenarios
- FTS5 provides excellent full-text search
- Async via aiosqlite (non-blocking I/O)
- For high-concurrency multi-user scenarios, the AWS deployment isolates each user to their own container (and thus their own SQLite instances)

### Why in-memory session clients?

The `sessions: dict[str, ClaudeSDKClient]` dictionary keeps SDK clients alive in memory. This enables:
- Instant session switching without re-creating clients
- Context preservation within a server process lifetime
- The `claude_session_id` in the DB enables cross-restart resumption

Trade-off: If the server process dies, in-memory clients are lost. But the SDK's session resumption mechanism (via `claude_session_id`) restores context on the next connect.

### Why soft-delete for memories?

`memory_forget` sets `active = 0` instead of deleting the row. This:
- Preserves audit history (what was known and when)
- Enables potential undo functionality
- Prevents accidental permanent data loss
- Queries filter on `active = 1` so "deleted" memories are invisible

### Why bypass permissions mode?

`permission_mode="bypassPermissions"` — the agent can use any tool without user approval. This is intentional:
- The system is designed for autonomous agent operation
- Safety hooks provide the guardrails (not permission prompts)
- User interaction is via chat, not terminal-style approve/deny
- Docker isolation provides an additional security boundary

### Why separate routes from websocket handlers?

REST endpoints (routes/) handle CRUD operations. WebSocket handlers (websocket.py, workflow_ws.py) handle streaming. This separation:
- Keeps files focused and small (<300 lines each)
- Makes it easy to add REST-only features without touching streaming code
- Allows the frontend to mix REST (initial data load) and WebSocket (real-time updates)

### Run Manager pattern (WebSocket-independent task lifecycle)

The `chat_run_manager.py` and `workflow_run_manager.py` modules manage agent task lifecycles independently of WebSocket connections. This is an important architectural pattern:

```
WebSocket connects → starts a run → WebSocket disconnects
                                        │
                                        ├─ Run continues in background (asyncio task)
                                        ├─ Results are persisted to DB
                                        │
WebSocket reconnects → attaches to the running task
                                        │
                                        └─ Resumes receiving streamed events
```

Key benefits:
- **Resilience** -- A dropped WebSocket connection does not cancel in-flight agent work. The run completes and results are saved regardless.
- **Reconnection** -- Clients can reconnect and reattach to a running task to resume receiving live events.
- **Shared patterns** -- `run_manager_utils.py` provides common attach/detach/cancel logic used by both chat and workflow run managers.
- **Concurrency** -- `workflow_run_manager.py` can execute multiple pipeline steps concurrently without tying up WebSocket handler coroutines.

This pattern replaces the earlier approach where the streaming loop ran directly inside the WebSocket message handler, which meant a disconnection would abort the entire agent run.

---

### Why CGEvent via PyObjC for macOS key delivery (not AppleScript):

The `macos_input.py` module uses CGEvent (via PyObjC) with a private event source state for all keyboard and scroll input. This was chosen over AppleScript (`osascript -e 'tell application "System Events" to keystroke ...'`) because:

- **Private event source state** -- CGEvents created with a private source bypass the system's event deduplication and key-repeat suppression, ensuring every keystroke is delivered exactly once.
- **Works with system UI** -- Spotlight, menu bar items, and other system-level UI elements reliably receive CGEvent-based keystrokes. AppleScript `keystroke` often fails to reach these targets.
- **No app addressing required** -- CGEvents are posted to the HID event stream and delivered to whatever window has focus, avoiding the need to `tell application X` (which can fail if the app name is wrong or the app is unresponsive).
- **Scroll wheel support** -- CGEvent provides native scroll wheel events (`kCGEventScrollWheel`), which correctly interact with momentum scrolling and per-pixel scroll views. There is no clean AppleScript equivalent.

Trade-off: PyObjC adds a native dependency, but it is pre-installed on macOS system Python and readily available via pip for virtual environments.

### Why the frontend is just a layer:

The entire system works via HTTP + WebSocket. The React frontend is one possible client. This enables:
- CLI-driven usage via curl
- Integration into other applications via API
- Mobile app development without backend changes
- Slack/Teams bot integration
- Automated testing via API calls
- Custom dashboards pointing at the same backend
