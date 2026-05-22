# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CGIAR Innovation Analytics Platform — a modular AI-powered analytics platform for CGIAR innovation portfolio management. Uses Claude Opus 4.6 via the Claude Agent SDK with specialist subagents. Deployed locally on macOS or at scale on AWS.

**Forked from** `cgiar-agent-synapsis` as the foundation platform (FastAPI + Claude Agent SDK + React 19 + shadcn/ui).

**Implementation plan:** `/Users/smithai/workspace/analysis/plan-innovation-analytics-platform.md`

### Four Modules (Planned)

1. **Conversational Data Interrogation** — Natural language access to the PRMS database (197 tables). Users ask questions about innovations, partners, geographies; the agent translates to SQL and returns sourced answers with PRMS-validated vs AI-inferred attribution.
2. **Self-Serve Visualization Builder** — Users request charts through conversation and get interactive Recharts-based visualizations. Bar, line, area, pie, scatter, map, heatmap.
3. **Scenario Planning** — Forward-looking "what if" analysis for portfolio decisions. Combines PRMS data with scaling readiness framework logic.
4. **Partner Identification** — Find external partners for scaling specific innovations. Combines PRMS partner data with web search.

### Data Source

- **PRMS Database:** SQLite at `/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite` (197 tables, ~398MB)
- **Schema docs:** `/Users/smithai/workspace/analysis/prms-database-discovery*.md` and `/Users/smithai/workspace/analysis/prms-schema-analysis.md`
- **Innovation export:** `/Users/smithai/workspace/uploads/CGIAR_inovationPRMS_export_data_table_results_edited_GA.xlsx`

## Build & Run Commands

### Native macOS

```bash
./start-innovation-analytics.sh    # checks prereqs, builds frontend, launches on port 7780
```

Or manually:

```bash
# Backend
pip install -r requirements-macos.txt
SYNAPSIS_PORT=7780 python app.py

# Frontend
cd frontend && npm install && npm run build && cd ..
```

**Prerequisites:**
- Python 3.11+ (`brew install python@3.11`)
- Node 20+ (`brew install node`)
- `cliclick` (`brew install cliclick`) — for computer use tools
- `pyobjc-framework-Quartz` (installed via `pip install -r requirements-macos.txt`)

The app runs on **port 7780** — FastAPI with WebSocket at `/ws/chat` and REST API at `/api/*`.

**IMPORTANT:** Do NOT run on port 7777 (production Synapsis Agent) or 7778 (CGIAR Demand-Supply Explorer).

### Testing

**Backend tests** use pytest with pytest-asyncio:

```bash
pytest                        # run all tests
pytest tests/test_hooks.py    # single file
pytest -v                     # verbose
```

**Frontend tests:** `cd frontend && npm test`

**Manual validation:**

```bash
python -c "from synapsis.server import app; print('OK')"
curl http://localhost:7780/api/health
```

## Architecture

### Backend (`synapsis/`)

Same modular package structure as the parent `cgiar-agent-synapsis` platform (~80 files across 11 sub-packages). Key modules:

- `app.py` — Thin entry point, imports and launches uvicorn
- `synapsis/server.py` — FastAPI assembly, router registration, startup, static mount
- `synapsis/system_prompt.py` — Main orchestrator system prompt builder
- `synapsis/agent_options.py` — ClaudeAgentOptions builder (tools, hooks, MCP, subagents)
- `synapsis/agents/definitions.py` — Subagent definitions
- `synapsis/database/` — SQLite persistence layer (chat.db + workflow_runs.db)
- `synapsis/tools/` — MCP server tools (memory, agent management, chat history, computer use)
- `synapsis/routes/` — REST API (15+ route modules)
- `synapsis/websocket.py` — `/ws/chat` streaming handler + session management

**Key design principles:**
- Each module is <300 lines
- Single responsibility per file
- Config centralized in `config.py` and `constants.py`
- Import direction: config/constants -> database/tools/hooks/agents -> agent_options -> services -> routes/websocket -> server -> app.py

### Frontend (`frontend/` -> built into `static/`)

React 19 + Vite 6 + Tailwind 3.4 + TypeScript 5.7 SPA with React Router.

Pages: Dashboard, Chat, Agents, Workflows, Fleet, Files, Settings.

State management: Zustand 5 (4 stores). WebSocket streaming with session management and reconnection.

For frontend development: `cd frontend && npm install && npm run dev` (proxies to backend).

After changes: `cd frontend && npm run build` to rebuild static files served by FastAPI.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNAPSIS_PORT` | `7780` | Server port (DO NOT use 7777 or 7778) |
| `SYNAPSIS_MODEL` | `claude-opus-4-6` | Primary orchestrator model |
| `SYNAPSIS_FALLBACK_MODEL` | `claude-sonnet-4-5-20250929` | Fallback model |
| `SYNAPSIS_PLATFORM` | auto (`macos` on Darwin) | Platform detection |
| `SYNAPSIS_WORKSPACE` | `~/workspace` on macOS | Working directory root |
| `SYNAPSIS_HOST` | `0.0.0.0` | Server bind address |
| `SYNAPSIS_MAX_SESSIONS` | `10` | Max concurrent sessions |
| `SYNAPSIS_LOG_LEVEL` | `INFO` | Log verbosity |

## Project Status

**Phase 0 -- Foundation.** Repo created, identity updated, builds confirmed. Next: PRMS data tool (Task 2) and CGIAR knowledge base (Task 3).
