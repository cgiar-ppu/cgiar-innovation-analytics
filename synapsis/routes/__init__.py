"""
Synapsis REST API routes — organized into focused routers.

Each module defines an APIRouter that gets included by the main server:
- health:      /api/health, /api/activity, /api/config
- files:       /api/upload, /api/files
- sessions:    /api/sessions, /api/history, /api/sessions/{id}/pin, /api/sessions/{id}/auto-title
- query:       /api/query (stateless single-shot)
- export:      /api/export/{session_id} (MD/HTML/DOCX/PDF)
- search:      /api/search (full-text conversation search)
- agents:      /api/personas (persona picker) + /api/agents (read; writes admin-only)
- transcribe:     /api/transcribe (voice-to-text via OpenAI)
- prms_dashboard: /api/dashboard/prms-* (the PRMS portfolio dashboard)
- scope:          /api/scope/options (year + programme filter values for the agent data scope)

Not registered in the IA app (Synapsis-agent leftovers, review 2026-09-23
L7-05; modules kept only until the frontend callers are removed): memories,
workflows, workflow_runs, workflow_logs, git, agent_query, skills, fleet,
images and dashboard (/api/dashboard/stats). tests/test_leftover_routes.py
pins their absence.
"""

from synapsis.routes.health import router as health_router
from synapsis.routes.files import router as files_router
from synapsis.routes.sessions import router as sessions_router
from synapsis.routes.query import router as query_router
from synapsis.routes.export import router as export_router
from synapsis.routes.search import router as search_router
from synapsis.routes.agents import router as agents_router
from synapsis.routes.transcribe import router as transcribe_router
from synapsis.routes.tts import router as tts_router
from synapsis.routes.prms_dashboard import router as prms_dashboard_router
from synapsis.routes.scope import router as scope_router

__all__ = [
    "health_router",
    "files_router",
    "sessions_router",
    "query_router",
    "export_router",
    "search_router",
    "agents_router",
    "transcribe_router",
    "tts_router",
    "prms_dashboard_router",
    "scope_router",
]
