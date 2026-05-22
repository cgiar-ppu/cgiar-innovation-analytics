"""
Synapsis Analytics Agent — Entry point.

This is a thin launcher that imports the assembled FastAPI app from the
synapsis package and starts uvicorn. All logic lives in the synapsis/ modules.

Module structure:
    synapsis/
    ├── __init__.py             — Package metadata
    ├── config.py               — All env vars, paths, logging, auth detection
    ├── constants.py            — Centralized magic values, app-wide settings
    ├── models.py               — Pydantic request/response models for REST API
    ├── system_prompt.py        — Main orchestrator system prompt builder
    ├── agent_options.py        — ClaudeAgentOptions builder (tools, hooks, MCP, subagents)
    ├── server.py               — FastAPI assembly, router registration, startup, static mount
    ├── websocket.py            — /ws/chat streaming handler + session management
    ├── workflow_ws.py          — /ws/workflow/{id} pipeline execution via WebSocket
    ├── ws_utils.py             — Shared WebSocket utilities
    ├── stream_handler.py       — Consumes async generator from ClaudeSDKClient
    ├── stream_core.py          — Shared streaming utilities for chat and workflow paths
    ├── stream_callbacks.py     — StreamCallbacks dependency injection container
    ├── message_handlers.py     — Process individual message blocks and SDK types
    ├── chat_run_manager.py     — Chat task lifecycle management (independent of WS)
    ├── workflow_run_manager.py — Concurrent pipeline execution management
    ├── run_manager_utils.py    — Shared attach/detach/cancel patterns
    ├── session_manager.py      — Backward-compatible re-export shim
    ├── db_manager.py           — Shared DB connection management boilerplate
    ├── workflow_db.py          — Workflow runs DB re-export shim
    ├── agents/
    │   ├── __init__.py         — Re-exports for backward compatibility
    │   ├── definitions.py      — 5 AgentDefinition objects + opus/sonnet variants
    │   ├── registry.py         — AGENT_REGISTRY, display metadata, get_agent_display_name
    │   └── loader.py           — load_all_agents (merges builtin + DB custom agents)
    ├── database/
    │   ├── __init__.py         — Re-exports all DB operations
    │   ├── connection.py       — Main chat DB connection management
    │   ├── schema.py           — Schema init and migrations (chat DB)
    │   ├── messages.py         — Message CRUD operations
    │   ├── sessions.py         — Session CRUD operations
    │   ├── memory.py           — Memory context loading for conversation injection
    │   ├── tasks.py            — Task status tracking for chat sessions
    │   ├── workflow_connection.py  — Workflow runs DB connection management
    │   ├── workflow_schema.py  — Schema init (workflow DB)
    │   ├── workflow_runs.py    — Workflow run CRUD operations
    │   ├── workflow_steps.py   — Workflow run step CRUD operations
    │   └── workflow_messages.py — Workflow run message operations
    ├── tools/
    │   ├── __init__.py         — Assembles MCP server with all tools
    │   ├── memory.py           — 4 memory MCP tools (store, recall, list, forget)
    │   ├── computer.py         — Unified computer use tool (routes to platform impl)
    │   ├── computer_macos.py   — macOS: screencapture + cliclick + osascript
    │   ├── computer_linux.py   — Linux: xdotool + xwd/import
    │   ├── computer_utils.py   — Shared computer use utilities
    │   ├── agents.py           — 3 agent MCP tools (create, list, update)
    │   └── slack.py            — Slack notification tool (wraps notify.sh)
    ├── hooks/
    │   ├── __init__.py         — Re-exports safety + audit hooks
    │   ├── safety.py           — Pre-tool dangerous command blocking
    │   └── audit.py            — Post-tool audit logging
    ├── routes/
    │   ├── __init__.py         — Exports all routers
    │   ├── health.py           — /api/health, /api/activity, /api/config
    │   ├── files.py            — /api/upload, /api/files, /api/files/{path}
    │   ├── sessions.py         — Session CRUD + /api/history
    │   ├── memories.py         — Memory CRUD REST API
    │   ├── query.py            — /api/query (stateless single-shot)
    │   ├── export.py           — /api/export (MD, HTML, DOCX, PDF)
    │   ├── search.py           — /api/search (full-text conversation search)
    │   ├── agents.py           — /api/agents CRUD + clone + test
    │   ├── dashboard.py        — /api/dashboard/stats, /api/dashboard/activity
    │   ├── workflows.py        — /api/workflows CRUD + run
    │   ├── workflow_runs.py    — /api/workflows/{id}/runs (DB-backed history)
    │   ├── workflow_logs.py    — /api/workflows/{id}/logs (file-based logs)
    │   ├── transcribe.py       — /api/transcribe (voice-to-text via OpenAI)
    │   └── git.py              — /api/git/status, diff, log, show
    ├── services/
    │   ├── __init__.py         — Business logic services
    │   ├── agent_service.py    — Agent creation and ID generation logic
    │   ├── search_service.py   — Search business logic
    │   ├── session_service.py  — Session business logic
    │   ├── workflow_service.py — Workflow business logic
    │   ├── workflow_executor.py — Multi-agent pipeline execution orchestrator
    │   ├── workflow_step_runner.py — Single-step execution logic
    │   ├── workflow_step_helpers.py — Step helper utilities
    │   ├── workflow_persistence.py — Run log file I/O + DB status updates
    │   └── workflow_stream_handler.py — Claude SDK response stream consumer
    ├── handlers/
    │   ├── __init__.py         — WebSocket message handler functions
    │   ├── chat_handlers.py    — WebSocket chat message handler functions
    │   └── utils.py            — Shared handler helpers
    ├── session/
    │   ├── __init__.py         — Re-exports SessionManager facade
    │   ├── manager.py          — SessionManager facade composing all registries
    │   ├── client_registry.py  — SDK client lifecycle + per-session locking
    │   ├── client_factory.py   — Client creation with retry logic
    │   ├── connection_registry.py — WebSocket connection tracking
    │   ├── broadcast.py        — Fan-out messages to WS connections
    │   └── cancel.py           — In-flight task + SDK client teardown
    ├── exporters/
    │   ├── __init__.py         — Re-exports all format exporters
    │   ├── common.py           — Shared exporter helpers
    │   ├── message_visitor.py  — Shared message visitor pattern
    │   ├── markdown.py         — Markdown format exporter
    │   ├── html.py             — HTML format exporter
    │   ├── docx.py             — DOCX format exporter
    │   └── workflow_run.py     — Workflow run log exporter (MD + HTML)
    ├── utils/
    │   ├── __init__.py         — Shared utility functions
    │   ├── db_helpers.py       — Shared DB helpers for routes
    │   └── responses.py        — Shared response builders for MCP tools
    └── validators/
        ├── __init__.py         — Input validation helpers
        └── agents.py           — Agent input validation helpers
"""

from synapsis.config import HOST, PORT, LOG_LEVEL, logger
from synapsis.server import app  # noqa: F401 — used by uvicorn

if __name__ == "__main__":
    import uvicorn

    # SSL termination is handled by the nginx reverse proxy (Let's Encrypt).
    # All backends serve plain HTTP — no self-signed certs needed.
    # The browser sees HTTPS from nginx, which satisfies secure-context
    # requirements (e.g. getUserMedia for voice-to-text). On localhost,
    # browsers treat HTTP as a secure context by spec (W3C Secure Contexts).
    logger.info("Starting Synapsis Analytics Agent on %s:%d", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level=LOG_LEVEL.lower())
