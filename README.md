# CGIAR Innovation Analytics Platform

Modular AI-powered analytics for CGIAR innovation portfolio management. Built on the Synapsis Agent platform (FastAPI + Claude Agent SDK + React 19 + shadcn/ui).

**Status: Phase 0 -- Foundation**

---

## Overview

The CGIAR Innovation Analytics Platform provides intelligent, conversational access to CGIAR's innovation portfolio data. It connects to the Performance Results Management System (PRMS) database and enables users to explore, analyze, and plan around CGIAR's innovation investments through natural language interaction.

### Four Modules

| Module | Description | Status |
|--------|-------------|--------|
| **Conversational Data Interrogation** | Ask natural language questions about CGIAR innovations, partners, and geographies. Get sourced answers with clear PRMS-validated vs AI-inferred attribution. | Planned |
| **Self-Serve Visualization Builder** | Request charts through conversation. Bar, line, area, pie, scatter, map, and heatmap visualizations rendered inline with interactive Recharts components. | Planned |
| **Scenario Planning** | Forward-looking "what if" analysis for portfolio decisions. Combines PRMS data with the scaling readiness framework for comparative before/after analysis. | Planned |
| **Partner Identification** | Find external partners for scaling specific innovations. Combines PRMS partner data with web search, clearly distinguishing data-sourced vs AI-suggested partners. | Planned |

## Tech Stack

- **Backend:** Python 3.11+ / FastAPI / WebSocket streaming / Claude Agent SDK (multi-agent orchestration)
- **Frontend:** React 19 / TypeScript 5.7 / Vite 6 / Tailwind 3.4 / shadcn/ui / Zustand 5
- **Data:** PRMS SQLite database (197 tables, ~398MB)
- **AI:** Claude Opus 4.6 orchestrator with specialist Sonnet subagents
- **Deployment:** Native macOS (development) / AWS (production, planned)

## Quick Start

### Prerequisites

- Python 3.11+ (`brew install python@3.11`)
- Node 20+ (`brew install node`)
- `cliclick` (`brew install cliclick`) -- for computer use tools
- Claude Code CLI authenticated (`claude login`)

### Install and Run

```bash
# Clone the repository
git clone git@github.com:cgiar-ppu/cgiar-innovation-analytics.git
cd cgiar-innovation-analytics

# Install backend dependencies
pip install -r requirements-macos.txt

# Install and build frontend
cd frontend && npm install && npm run build && cd ..

# Start the platform (port 7780)
./start-innovation-analytics.sh
```

Or start manually:

```bash
SYNAPSIS_PORT=7780 python app.py
```

Then open http://localhost:7780 in your browser.

## Architecture

### Agent-Based Approach

The platform uses a multi-agent architecture powered by the Claude Agent SDK:

- **Orchestrator (Opus 4.6):** Routes user requests to the appropriate specialist subagent based on the task type. Maintains conversation context and coordinates multi-step analyses.
- **Specialist Subagents (Sonnet):** Domain-focused agents for data analysis, visualization, research methodology, code automation, and computer use. Each has a tailored system prompt and tool access.
- **MCP Tools:** Memory persistence, agent management, chat history search, and desktop interaction -- all exposed as Model Context Protocol servers.

### Data Source: PRMS

The platform queries the CGIAR Performance Results Management System (PRMS) database, which contains:

- Innovation records with metadata (type, readiness level, geography, partners)
- Science programme and initiative linkages
- Partner and funder relationships
- Geographic coverage at country, region, and global levels
- Results and output tracking across CGIAR centers

The PRMS database has 197 tables with comprehensive coverage of CGIAR's research-for-development portfolio.

## Project Structure

```
cgiar-innovation-analytics/
  app.py                    # FastAPI entry point
  synapsis/                 # Backend package (~80 modules)
    server.py               # FastAPI assembly
    websocket.py            # WebSocket streaming
    agents/                 # Subagent definitions
    database/               # SQLite persistence
    tools/                  # MCP server tools
    routes/                 # REST API endpoints
    ...
  frontend/                 # React 19 SPA
    src/
      pages/                # Dashboard, Chat, Agents, etc.
      components/           # UI component library
      stores/               # Zustand state management
      hooks/                # WebSocket, API, routing
      lib/                  # Types, utilities, API client
  references/               # Analytics templates and guides
  infra/                    # AWS CloudFormation + Lambda
  tests/                    # Backend pytest suite
```

## Development

See [CLAUDE.md](./CLAUDE.md) for detailed development guidance, architecture documentation, and environment variable reference.

## Configuration

Key environment variables (set in `.env` or export before running):

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNAPSIS_PORT` | `7780` | Server port |
| `SYNAPSIS_MODEL` | `claude-opus-4-6` | Primary orchestrator model |
| `SYNAPSIS_FALLBACK_MODEL` | `claude-sonnet-4-5-20250929` | Fallback model |
| `SYNAPSIS_MAX_TURNS` | `200` | Max agentic turns per conversation |
| `SYNAPSIS_LOG_LEVEL` | `INFO` | Log verbosity |

## Testing

```bash
# Backend
pytest -v

# Frontend
cd frontend && npm test
```

## License

Proprietary -- CGIAR / Synapsis Analytics.
