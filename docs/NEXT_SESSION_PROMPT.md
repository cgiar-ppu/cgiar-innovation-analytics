# Prompt for Next AI Session — Synapsis Agent v2 Enhancement

> Copy everything below this line and give it to the next AI agent as the opening prompt.

---

## Context

You are working on the repository at `~/smithai/workspace/synapsis-agent-macos-v2`. This is a multi-agent analytics platform built with:
- **Backend:** Python FastAPI + Claude Agent SDK (Claude Opus 4.6 orchestrator + 5 Sonnet subagents)
- **Frontend:** React 19 + TypeScript + Vite + Tailwind + React Router (6-page SPA)
- **Database:** SQLite (sessions, messages, memories, workflows)
- **Deployment:** Local Docker, native macOS, or AWS (EC2 ASG + Lambda)

Read `CLAUDE.md` first for full project context. Then read `docs/ROADMAP.md` for the detailed implementation plan. Then read `docs/API_REFERENCE.md` and `docs/ARCHITECTURE.md` for how everything works.

## What Was Just Done (Previous Session)

The repo was upgraded from a single-page chat app to a multi-page SPA. Here's what was added:
- React Router with 6 pages: Dashboard (`/`), Chat (`/chat`), Agents (`/agents`), Workflows (`/workflows`), Files (`/files`), Settings (`/settings`)
- TopBar navigation with animated pills (framer-motion), CommandPalette (Cmd+K)
- Dashboard page with Recharts activity chart, animated stats cards
- Agents page with visual grid, search, detail modal
- Workflows page with React Flow canvas, create modal, PipelineRunner modal
- Files page with upload/download, file type icons
- Settings page with theme toggle, model info
- `useApi` hook with mock data fallback for graceful offline degradation
- Service layer (dashboard.ts, agents.ts, workflows.ts, files.ts)
- Reference templates directory (analysis_report_template.md, handoff_template.md, workflow_design_guide.md, best_practices.md)
- Backend: `/api/dashboard/activity` endpoint, SPA catch-all route, improved code splitting

## Known Issues to Fix First

### Issue 1: Orphaned Header.tsx
`frontend/src/components/layout/Header.tsx` exists but is NOT imported anywhere. It was replaced by `TopBar.tsx` but TopBar lost several features that Header had:
- **Detailed connection status** (Wifi/WifiOff icons, status text like "Connected"/"Reconnecting...", colored dots)
- **Desktop panel toggle** (Monitor icon button that calls `toggleDesktopPanel()` from the ui store)
- **Search button** (Search icon with Cmd+K hint)
- **Auth method badge** (shows "Pro", "API", or "No Auth")
- **Model badge** (shows current model name)

**Fix:** Merge these features into TopBar.tsx, then delete Header.tsx.

### Issue 2: WebSocket Only in Chat Page
`useWebSocket()` is only called inside `pages/Chat.tsx`. This means TopBar can't show real connection status — it shows a static green dot. Other pages can't know if the backend is connected.

**Fix:** Create a React Context (`contexts/WebSocketContext.tsx`) that wraps the app in Layout.tsx. The WebSocket hook lives there. TopBar consumes the context for status. Chat.tsx consumes it for send/receive.

### Issue 3: DesktopViewer Only in Chat Page
The VNC/Desktop viewer (`components/desktop/DesktopViewer.tsx`) is only rendered inside Chat.tsx. If a workflow triggers computer_use, there's no way to see the desktop from the Workflows page.

**Fix:** Move DesktopViewer into Layout.tsx so it's globally available. It already checks `config?.vnc_available && desktopPanelOpen` before rendering. Chat.tsx should stop rendering it (Layout handles it now).

## Main Implementation Tasks (in priority order)

### Task 1: Fix Regressions (Issues 1-3 above)
Do these first before anything else. They're small fixes that make the app actually work properly.

### Task 2: Dynamic Agent Creation & Persistence

**Goal:** Users can create custom agents that persist in the database and are available to the orchestrator at runtime.

#### 2a. Database — Add `agents` table:
In `synapsis/database.py`, add to `init_db()`:
```sql
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    tools TEXT DEFAULT '[]',
    model TEXT DEFAULT 'sonnet',
    color TEXT DEFAULT '#6366f1',
    type TEXT DEFAULT 'custom',
    is_active INTEGER DEFAULT 1,
    created_at REAL,
    updated_at REAL,
    created_by TEXT DEFAULT '',
    parent_agent TEXT DEFAULT '',
    version INTEGER DEFAULT 1
);
```

#### 2b. Agent CRUD API:
Extend `synapsis/routes/agents.py` with:
- `POST /api/agents` — Create custom agent (validate tools against allowed list)
- `PUT /api/agents/{id}` — Update custom agent (block updates to builtin agents)
- `DELETE /api/agents/{id}` — Soft-delete (set is_active=0, block delete of builtins)
- `POST /api/agents/{id}/clone` — Clone any agent (builtin or custom) as a new custom agent
- `POST /api/agents/{id}/test` — Send a test message using this agent's config (stateless)

The `GET /api/agents` endpoint should merge builtin agents (from `agents.py` SUBAGENTS dict) with custom agents from DB. Builtins have `type: "builtin"`, customs have `type: "custom"`.

#### 2c. Dynamic Agent Loading:
In `synapsis/agents.py`, add:
```python
async def load_all_agents() -> dict:
    """Merge builtin SUBAGENTS with custom agents from DB."""
    custom = await _load_custom_agents_from_db()
    merged = dict(SUBAGENTS)
    for agent in custom:
        merged[agent["id"]] = AgentDefinition(
            description=agent["description"],
            prompt=agent["system_prompt"],
            tools=json.loads(agent["tools"]),
            model=agent["model"],
        )
    return merged
```

Modify `synapsis/agent_options.py` → `build_agent_options()` to call `load_all_agents()` and pass the merged dict as `agents=`.

Modify `synapsis/system_prompt.py` → `build_system_prompt()` to accept the agents dict and dynamically list all available agents in the routing section.

#### 2d. MCP Tools for Agent Creation:
Create `synapsis/tools/agents.py` with 3 tools:
- `mcp__synapsis__agent_create(name, description, system_prompt, tools, model)` — Create agent from within conversation
- `mcp__synapsis__agent_list()` — List all agents (so the AI knows what's available)
- `mcp__synapsis__agent_update(id, ...)` — Update a custom agent

Register in `synapsis/tools/__init__.py` and add to allowed_tools in `agent_options.py`.

Update the system prompt to tell the orchestrator it can create specialized agents on the fly.

#### 2e. Frontend — Agent Create/Edit UI:
Create `frontend/src/components/agents/AgentCreateModal.tsx`:
- Form fields: name, description, system prompt (large textarea), tools (multi-select checkboxes), model (dropdown: sonnet/opus), color picker
- Available tools list: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch (these are the standard tools any subagent can have)
- Save calls `POST /api/agents`

Create `frontend/src/components/agents/AgentEditModal.tsx` — same form, pre-filled.

Update `frontend/src/pages/Agents.tsx`:
- Add "Create Agent" button in the header
- Add edit/delete/clone buttons on custom agent cards (not on builtin cards)
- Add a visual distinction between builtin and custom agents (e.g., a "Custom" badge)

Update `frontend/src/services/agents.ts` with createAgent, updateAgent, deleteAgent, cloneAgent, testAgent methods.

### Task 3: Orchestrator as Workflow Step

**Goal:** The main orchestrator (Opus with all subagents) can be a step in a workflow, making each step a full agentic team.

#### 3a. Backend:
In `synapsis/workflow_ws.py`, modify the step execution loop. Currently it always overrides the system prompt:
```python
opts.system_prompt = agent_def.prompt
```

Add a special case: if `agent_id == "orchestrator"`, use the FULL `build_agent_options()` without overriding the system prompt. This gives the step access to all subagents, memory, computer use, etc.

```python
if agent_id == "orchestrator":
    opts = await build_agent_options()  # Full orchestrator with all subagents
    if step_config.get("extra_instructions"):
        opts.system_prompt += f"\n\n## Additional Instructions for This Step\n{step_config['extra_instructions']}"
    if step_config.get("sub_agents"):
        # Filter agents dict to only include specified subagents
        opts.agents = {k: v for k, v in opts.agents.items() if k in step_config["sub_agents"]}
else:
    # Existing behavior: single subagent with overridden prompt
    ...
```

#### 3b. Per-Step Configuration:
Add `step_configs` column to workflows table (JSON text, default '[]').

Each element:
```json
{
    "agent_id": "orchestrator",
    "sub_agents": ["data_analysis", "visualization_reporting"],
    "extra_instructions": "Focus on statistical significance",
    "max_turns": 50
}
```

Modify the workflow create/update endpoints to accept this.

#### 3c. Frontend — Step Configurator:
Create `frontend/src/components/workflows/StepConfigurator.tsx`:
- When user selects "orchestrator" as a workflow step, show additional options:
  - Which subagents to include (checkboxes)
  - Extra instructions (textarea)
  - Max turns (number input)
- For regular subagent steps, show just extra instructions

Update the create workflow modal in `frontend/src/pages/Workflows.tsx` to use StepConfigurator.

#### 3d. Enhanced Inter-Step Handoff:
In `synapsis/workflow_ws.py`, improve the prompt passed between steps:
```python
step_prompt = f"""## Context from Previous Step

**Agent:** {previous_agent_name}
**Step {step_idx} of {total_steps}**

### Previous Agent's Output:
{current_prompt}

---

Now continue with your expertise. Build on the previous analysis. You have access to any files the previous agent created in the workspace.
"""
```

### Task 4: Agent List in Orchestrator System Prompt

**Goal:** The system prompt dynamically lists all available agents so the orchestrator knows what it can delegate to, including custom agents.

In `synapsis/system_prompt.py`, change the hardcoded agent routing section to be dynamically generated:

```python
def build_system_prompt(agents_dict: dict) -> str:
    agent_list = ""
    for agent_id, agent_def in agents_dict.items():
        agent_list += f"   - **{agent_id}**: {agent_def.description}\n"

    # Insert into the routing section of the prompt
    ...
```

This means when a user creates a custom "financial_analyst" agent, the orchestrator's prompt automatically includes it in the routing options.

## Architecture Notes

### Key files to understand before starting:

| File | Lines | What it does |
|------|-------|-------------|
| `synapsis/agents.py` | ~276 | Builtin subagent definitions + shared tool lists |
| `synapsis/agent_options.py` | ~80 | Builds ClaudeAgentOptions (tools, hooks, MCP, subagents) |
| `synapsis/system_prompt.py` | ~100 | Orchestrator system prompt template |
| `synapsis/workflow_ws.py` | ~200 | WebSocket workflow pipeline execution |
| `synapsis/database.py` | ~340 | SQLite schema + CRUD helpers |
| `synapsis/tools/__init__.py` | ~20 | MCP server assembly |
| `synapsis/tools/memory.py` | ~220 | Memory MCP tools (pattern to follow for agent tools) |
| `synapsis/routes/agents.py` | ~83 | Current agents API (read-only) |
| `frontend/src/pages/Agents.tsx` | ~70 | Current agents page |
| `frontend/src/pages/Workflows.tsx` | ~200 | Current workflows page |
| `frontend/src/components/layout/TopBar.tsx` | ~60 | Current navigation bar |
| `frontend/src/components/layout/Header.tsx` | ~150 | **ORPHANED** — has features to merge into TopBar |
| `frontend/src/hooks/useWebSocket.ts` | ~150 | WebSocket with reconnection |
| `frontend/src/stores/ui.ts` | ~40 | UI state (theme, sidebar, desktopPanel) |

### Patterns to follow:
- **MCP tools:** Look at `synapsis/tools/memory.py` for the exact pattern (decorator, args dict, return format)
- **Route routers:** Look at `synapsis/routes/memories.py` for the CRUD pattern
- **Frontend services:** Look at `frontend/src/services/workflows.ts` for the fetch pattern
- **Frontend components:** Look at `frontend/src/components/agents/AgentCard.tsx` for the card pattern
- **Modals:** Look at `frontend/src/components/agents/AgentDetailModal.tsx` for the modal pattern
- **useApi hook:** Look at `frontend/src/pages/Dashboard.tsx` for the mock fallback pattern

### Import conventions:
- Backend: absolute imports from `synapsis.*`
- Frontend components: `export default function ComponentName()` (default exports)
- Frontend stores: `export const useXxxStore = create<XxxState>(...)` (named exports)
- Frontend lib: `export const api = {...}` (named exports)
- Frontend hooks: `export function useXxx()` (named exports)
- **Exception:** Some existing components use named exports: `export function Sidebar()`, `export function ChatArea()`, `export function DesktopViewer()`, `export function SearchPanel()`. Check the actual file before importing.

### Build & verify:
```bash
# Frontend build (from frontend/):
npm run build
# Should produce zero TypeScript errors

# Backend import check:
python -c "from synapsis.server import app; print('OK')"

# Run the app (native macOS):
./start-macos.sh
```

## Success Criteria

After implementation, the system should support this workflow:

1. User says: "Create me a financial analysis agent that specializes in SEC filings"
2. Orchestrator creates the agent via `mcp__synapsis__agent_create`
3. The new agent appears on the Agents page with a "Custom" badge
4. User creates a workflow: `orchestrator (with data_analysis + custom_financial_analyst) → visualization_reporting`
5. User runs the workflow — Step 1 is a full agentic team where the orchestrator delegates between data_analysis and the custom financial agent
6. Step 2 receives the analysis and creates visualizations
7. The desktop viewer (if VNC is available) is accessible from any page during execution
8. TopBar shows live connection status throughout

---

*This prompt was auto-generated from the Synapsis v2 roadmap session. See docs/ROADMAP.md for the full phased plan.*
