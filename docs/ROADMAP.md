# Synapsis Agent v2 — Roadmap to Full Capability

> Detailed plan to bring Synapsis to full parity with IWMI Coscientist capabilities, then surpass it with advanced multi-agent orchestration.

---

## Current State Assessment

### What Works
- 6-page React SPA (Dashboard, Chat, Agents, Workflows, Files, Settings)
- 5 hardcoded specialist subagents (data, viz, research, code, computer_use)
- Sequential workflow pipelines via WebSocket
- Persistent memory system (SQLite + FTS5)
- Desktop automation (macOS native + Linux VNC)
- Session management with SDK resumption
- Safety hooks + audit logging
- Mock data graceful degradation
- AWS multi-user deployment

### What's Broken or Missing
1. **Header.tsx is orphaned** — old Header component exists but nothing imports it; TopBar replaced it but lost some features (detailed connection status, desktop toggle, search button, auth badge)
2. **TopBar lacks features** — no desktop toggle, no search trigger, no auth badge, no model display
3. **Chat page missing Header features** — no way to toggle desktop panel, see model info, or trigger search from the chat page specifically
4. **Workflows only support subagents** — cannot include the main orchestrator as a pipeline step
5. **No dynamic agent creation** — agents are hardcoded in agents.py; users can't create custom agents
6. **No agent persistence** — custom agents can't be saved to DB and recalled across sessions
7. **No agentic teams** — workflow steps are single agents, not teams of agents collaborating
8. **No ad-hoc subagent selection** — each workflow step uses a fixed agent, not an orchestrator that picks helpers

---

## Phase 1: Fix Regressions & Polish (Priority: Immediate)

### 1.1 Restore Lost Header Features into TopBar

The old `Header.tsx` had features the new `TopBar.tsx` lost. Merge them:

**Files to modify:**
- `frontend/src/components/layout/TopBar.tsx` — Add: connection status with detail (Wifi/WifiOff + text), desktop panel toggle (Monitor icon), search button (Cmd+K), auth method badge, model badge
- `frontend/src/pages/Chat.tsx` — Ensure desktop toggle works from TopBar
- `frontend/src/stores/ui.ts` — Already has `desktopPanelOpen` and `toggleDesktopPanel`

**After this:** Delete the orphaned `frontend/src/components/layout/Header.tsx`

### 1.2 Wire Up WebSocket in TopBar

TopBar currently shows a static green dot. It needs the real connection status:

**Approach:** Create a global WebSocket context (React Context) so the connection state is available to both TopBar (for the indicator) and Chat page (for sending messages). Currently `useWebSocket` is only called inside Chat.tsx.

**Files to create/modify:**
- `frontend/src/contexts/WebSocketContext.tsx` — New context provider wrapping the app
- `frontend/src/components/layout/Layout.tsx` — Wrap Outlet with WebSocketProvider
- `frontend/src/components/layout/TopBar.tsx` — Consume context for connection status
- `frontend/src/pages/Chat.tsx` — Use context instead of direct hook call

### 1.3 Ensure VNC/Desktop Panel Works from Any Page

The DesktopViewer is currently only rendered inside Chat.tsx. For computer_use tasks triggered from workflows, it should be accessible globally.

**Approach:** Move DesktopViewer into Layout.tsx so it's available on all pages:

**Files to modify:**
- `frontend/src/components/layout/Layout.tsx` — Add DesktopViewer (conditional on config.vnc_available + desktopPanelOpen)
- `frontend/src/pages/Chat.tsx` — Remove DesktopViewer from here (now in Layout)

---

## Phase 2: Dynamic Agent Creation & Persistence (Priority: High)

### 2.1 Database Schema for Custom Agents

Add a new `agents` table so users can create, edit, and persist custom agents:

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,              -- e.g., "custom_financial_analyst"
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    system_prompt TEXT NOT NULL,       -- Full system prompt for this agent
    tools TEXT DEFAULT '[]',           -- JSON array of allowed tool names
    model TEXT DEFAULT 'sonnet',       -- Model to use
    color TEXT DEFAULT '#6366f1',      -- Display color (hex)
    type TEXT DEFAULT 'custom',        -- 'builtin' or 'custom'
    is_active INTEGER DEFAULT 1,
    created_at REAL,
    updated_at REAL,
    created_by TEXT DEFAULT '',        -- Session that created it
    parent_agent TEXT DEFAULT '',      -- If cloned from another agent
    version INTEGER DEFAULT 1
);
```

**Files to modify:**
- `synapsis/database.py` — Add table creation + CRUD functions
- `synapsis/constants.py` — Add AVAILABLE_TOOLS list for validation

### 2.2 Agent CRUD API

Full REST API for custom agent management:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/agents` | GET | List all agents (builtin + custom) |
| `POST /api/agents` | POST | Create a custom agent |
| `PUT /api/agents/{id}` | PUT | Update a custom agent |
| `DELETE /api/agents/{id}` | DELETE | Delete a custom agent (soft-delete) |
| `POST /api/agents/{id}/clone` | POST | Clone an existing agent as a starting point |
| `POST /api/agents/{id}/test` | POST | Send a test message to an agent (stateless) |

**Files to modify:**
- `synapsis/routes/agents.py` — Add POST, PUT, DELETE, clone, test endpoints
- `synapsis/models.py` — Add AgentCreate, AgentUpdate Pydantic models

### 2.3 Dynamic Agent Registration

Make the orchestrator aware of custom agents at runtime:

**Approach:** On each session creation, load custom agents from DB and merge with builtin agents before passing to `build_agent_options()`:

**Files to modify:**
- `synapsis/agents.py` — Add `load_custom_agents()` async function that reads from DB
- `synapsis/agent_options.py` — Call `load_custom_agents()` and merge with SUBAGENTS dict
- `synapsis/system_prompt.py` — Dynamically list all available agents (builtin + custom) in the system prompt

### 2.4 Agent Creation UI

Frontend page for creating and managing agents:

**Files to create:**
- `frontend/src/pages/Agents.tsx` — Extend with "Create Agent" button and form
- `frontend/src/components/agents/AgentCreateModal.tsx` — Modal with: name, description, system prompt editor (textarea with syntax hints), tool selector (checkboxes), model selector, color picker
- `frontend/src/components/agents/AgentEditModal.tsx` — Same as create but pre-filled
- `frontend/src/services/agents.ts` — Add createAgent, updateAgent, deleteAgent, cloneAgent, testAgent methods

### 2.5 Agent Creation via Chat

Allow the AI itself to create agents through conversation:

**New MCP Tool:**
- `mcp__synapsis__agent_create` — Create a new custom agent from within a conversation
- `mcp__synapsis__agent_list` — List all available agents (builtin + custom)
- `mcp__synapsis__agent_update` — Modify an existing custom agent

**Files to create/modify:**
- `synapsis/tools/agents.py` — New file with 3 MCP tools
- `synapsis/tools/__init__.py` — Register new tools
- `synapsis/agent_options.py` — Add to allowed_tools
- `synapsis/system_prompt.py` — Document the agent creation tools

This enables conversations like:
> "Create me a specialized agent for financial analysis that knows about SEC filings and GAAP standards"

The orchestrator creates the agent, and it's immediately available for routing.

---

## Phase 3: Orchestrator-as-Workflow-Step (Priority: High)

### 3.1 Include Main Orchestrator in Workflows

Currently, workflows only run subagents. The main orchestrator (Opus) should be an option too, since it can delegate to any subagent itself.

**Why this matters:** A workflow step powered by the orchestrator is actually a **full agentic team** — it can think, delegate to specialists, use memory, and coordinate. This is far more powerful than a single subagent step.

**Implementation:**

**Files to modify:**
- `synapsis/workflow_ws.py` — When `agent_id == "orchestrator"`, use the full `build_agent_options()` instead of overriding the system prompt. The orchestrator step gets all subagents, memory tools, and computer use.
- `synapsis/routes/agents.py` — Add `"orchestrator"` to the agent list with special metadata
- `frontend/src/lib/mockData.ts` — Add orchestrator to mock agents

### 3.2 Per-Step Agent Configuration

Allow each workflow step to optionally specify:
- Which subagents are available to it (if it's an orchestrator step)
- Custom instructions that augment (not replace) the agent's system prompt
- Max turns per step
- Whether to include memory context

**Schema extension:**
```sql
ALTER TABLE workflows ADD COLUMN step_configs TEXT DEFAULT '[]';
-- JSON: [{"agent_id": "orchestrator", "sub_agents": ["data_analysis", "viz"], "extra_instructions": "Focus on...", "max_turns": 50}]
```

**Files to modify:**
- `synapsis/workflow_ws.py` — Read step_configs and apply per-step overrides
- `synapsis/routes/workflows.py` — Accept step_configs in create/update
- `frontend/src/pages/Workflows.tsx` — Step configuration UI in create modal

---

## Phase 4: Agentic Teams & Collaboration (Priority: Medium-High)

### 4.1 Team-Based Workflow Steps

Each workflow step can be a **team** rather than a single agent:

```
Step 1: Research Team
  ├── Orchestrator (Opus) — coordinates
  ├── research_methodology — designs study
  └── data_analysis — validates feasibility

Step 2: Execution Team
  ├── Orchestrator (Opus) — coordinates
  ├── code_automation — builds pipeline
  └── data_analysis — runs analysis

Step 3: Reporting
  └── visualization_reporting — creates final report
```

**Implementation approach:**
- An orchestrator step already IS a team (it has access to all subagents via Task tool)
- The per-step config (Phase 3.2) controls which subagents are available
- The `extra_instructions` field tells the orchestrator how to coordinate

**No new backend architecture needed** — this is a configuration concern. The key is making the frontend and workflow creation UX expose this clearly.

### 4.2 Ad-Hoc Subagent Selection per Step

When creating a workflow, each orchestrator step should let users pick which subagents are available:

**Frontend changes:**
- `frontend/src/pages/Workflows.tsx` — In the create modal, when an "orchestrator" step is selected, show a sub-panel for selecting which subagents it can delegate to
- `frontend/src/components/workflows/StepConfigurator.tsx` — New component: agent selector, extra instructions textarea, max turns slider

### 4.3 Inter-Step Communication Enhancement

Currently, step N's entire text output is passed as a single string to step N+1. Enhance this:

**Structured handoff:**
```python
step_prompt = f"""
## Context from Previous Step

**Agent:** {previous_agent_name}
**Task:** {step_config.get('description', 'N/A')}

### Output:
{current_prompt}

### Files Created:
{list_workspace_files_created_during_step()}

---

Now continue with your expertise. You have access to all files the previous agent created.
"""
```

**Files to modify:**
- `synapsis/workflow_ws.py` — Enhanced prompt template with structured context

---

## Phase 5: Advanced Features (Priority: Medium)

### 5.1 Workflow Templates

Pre-built workflow templates users can instantiate:

**Files to create:**
- `synapsis/routes/workflow_templates.py` — CRUD for templates
- `references/workflow_templates/` — Directory of JSON template files
- Template examples:
  - `data_pipeline.json` — Scrape → Clean → Analyze → Visualize
  - `research_cycle.json` — Design → Power Analysis → Data Collection Plan → Report
  - `report_generation.json` — Analyze → Write → Format → Export

### 5.2 Workflow Branching (Conditional Steps)

Allow steps to have conditions — e.g., "if the data analysis finds significance, run visualization; otherwise, run more data collection":

**This is complex** — defer to a future version. For now, document it as a known limitation.

### 5.3 Parallel Workflow Steps

Allow independent steps to run concurrently:

```
Step 1: data_analysis (sequential)
  ├── Step 2a: visualization_reporting (parallel)
  └── Step 2b: code_automation (parallel)
Step 3: orchestrator — synthesize (sequential, waits for 2a + 2b)
```

**This requires significant architecture changes** — defer to future version.

### 5.4 Confidence Framework

Adapt IWMI's GREEN/AMBER/RED confidence system for general use:

**Files to modify:**
- `synapsis/system_prompt.py` — Add confidence assessment instructions
- `references/analysis_report_template.md` — Already has confidence section (done)

### 5.5 Agent Skills / Reusable Prompts

Let users save reusable prompt snippets ("skills") that can be attached to agents or workflow steps:

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    prompt_template TEXT NOT NULL,     -- Template with {{variables}}
    variables TEXT DEFAULT '[]',       -- JSON array of variable names
    category TEXT DEFAULT 'general',
    created_at REAL,
    updated_at REAL
);
```

**New MCP tool:** `mcp__synapsis__skill_use` — inject a skill's prompt into the current conversation.

---

## Phase 6: Robustness & Production Hardening (Priority: Medium)

### 6.1 Error Recovery in Pipelines

- If a workflow step fails, offer: retry, skip, or abort
- Save partial pipeline results so completed steps aren't lost
- Add step-level timeout configuration

### 6.2 Workflow Execution History

Store pipeline execution history (not just the latest status):

```sql
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    status TEXT,
    started_at REAL,
    completed_at REAL,
    total_duration_s REAL,
    step_results TEXT,     -- JSON: [{step, agent_id, output_preview, duration_s, status}]
    prompt TEXT,
    error TEXT
);
```

### 6.3 Rate Limiting

Add request rate limiting for multi-user deployments:
- Per-connection WebSocket message rate limit
- Per-IP REST API rate limit
- Configurable via environment variables

### 6.4 Searchable Audit Log

Move audit logs from flat file to SQLite:

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    ts REAL,
    session_id TEXT,
    event_type TEXT,    -- PreToolUse, PostToolUse
    tool_name TEXT,
    input_summary TEXT,
    output_summary TEXT
);
```

Add `/api/audit` endpoint and an audit viewer in the frontend.

---

## Implementation Priority Order

| Priority | Phase | Effort | Impact |
|----------|-------|--------|--------|
| 1 | 1.1 Restore TopBar features | Small (1-2 hours) | Fixes UX regression |
| 2 | 1.2 Global WebSocket context | Small (1-2 hours) | Fixes architecture gap |
| 3 | 1.3 Global DesktopViewer | Small (30 min) | Fixes VNC access |
| 4 | 3.1 Orchestrator in workflows | Medium (2-3 hours) | Unlocks agentic teams |
| 5 | 2.1-2.3 Agent DB + API + dynamic loading | Medium (3-4 hours) | Core new capability |
| 6 | 2.5 Agent creation via chat (MCP tools) | Medium (2-3 hours) | Powerful UX |
| 7 | 2.4 Agent creation UI | Medium (2-3 hours) | Visual agent management |
| 8 | 3.2 Per-step agent config | Medium (2-3 hours) | Workflow power |
| 9 | 4.1-4.3 Agentic teams + handoff | Medium (3-4 hours) | Advanced orchestration |
| 10 | 5.1 Workflow templates | Small (1-2 hours) | UX convenience |
| 11 | 5.4 Confidence framework | Small (1 hour) | Quality signals |
| 12 | 5.5 Skills system | Medium (3-4 hours) | Reusability |
| 13 | 6.1-6.4 Production hardening | Large (5-8 hours) | Robustness |

**Total estimated effort:** ~30-40 hours of focused development

---

## Files Inventory

### Files to Delete
- `frontend/src/components/layout/Header.tsx` (orphaned, replaced by TopBar)

### New Files to Create
- `frontend/src/contexts/WebSocketContext.tsx`
- `frontend/src/components/agents/AgentCreateModal.tsx`
- `frontend/src/components/agents/AgentEditModal.tsx`
- `frontend/src/components/workflows/StepConfigurator.tsx`
- `synapsis/tools/agents.py` (MCP tools for agent CRUD)
- `synapsis/routes/workflow_templates.py`
- `references/workflow_templates/*.json`

### Files to Modify (Major)
- `synapsis/database.py` — Add agents table, workflow_runs table, audit_log table, skills table
- `synapsis/routes/agents.py` — Full CRUD + clone + test
- `synapsis/agents.py` — Dynamic agent loading from DB
- `synapsis/agent_options.py` — Merge custom agents, new MCP tools
- `synapsis/system_prompt.py` — Dynamic agent listing, confidence framework, agent creation docs
- `synapsis/workflow_ws.py` — Orchestrator steps, per-step config, enhanced handoff
- `synapsis/tools/__init__.py` — Register agent CRUD tools
- `frontend/src/components/layout/TopBar.tsx` — Full Header features
- `frontend/src/components/layout/Layout.tsx` — WebSocket context + global DesktopViewer
- `frontend/src/pages/Agents.tsx` — Create/edit/delete UI
- `frontend/src/pages/Workflows.tsx` — Step configurator, orchestrator option
- `frontend/src/services/agents.ts` — Full CRUD client
