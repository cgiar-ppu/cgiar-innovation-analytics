"""
Synapsis REST API routes — organized into focused routers.

Each module defines an APIRouter that gets included by the main server:
- health:      /api/health, /api/activity, /api/config
- files:       /api/upload, /api/files
- sessions:    /api/sessions, /api/history, /api/sessions/{id}/pin, /api/sessions/{id}/auto-title
- memories:    /api/memories
- query:       /api/query (stateless single-shot)
- export:      /api/export/{session_id} (MD/HTML/DOCX/PDF)
- search:      /api/search (full-text conversation search)
- agents:      /api/agents (sub-agent browsing & details)
- dashboard:   /api/dashboard/stats (aggregate statistics)
- workflows:      /api/workflows (workflow CRUD)
- workflow_runs:  /api/workflows/{id}/runs (DB-backed run history)
- transcribe:     /api/transcribe (voice-to-text via OpenAI)
- git:            /api/git/status, /api/git/diff, /api/git/log, /api/git/show
- skills:         /api/skills (skill/command discovery for autocomplete)
"""

from synapsis.routes.health import router as health_router
from synapsis.routes.files import router as files_router
from synapsis.routes.sessions import router as sessions_router
from synapsis.routes.memories import router as memories_router
from synapsis.routes.query import router as query_router
from synapsis.routes.export import router as export_router
from synapsis.routes.search import router as search_router
from synapsis.routes.agents import router as agents_router
from synapsis.routes.dashboard import router as dashboard_router
from synapsis.routes.workflows import router as workflows_router
from synapsis.routes.workflow_runs import router as workflow_runs_router
from synapsis.routes.transcribe import router as transcribe_router
from synapsis.routes.tts import router as tts_router
from synapsis.routes.git import router as git_router
from synapsis.routes.agent_query import router as agent_query_router
from synapsis.routes.skills import router as skills_router
from synapsis.routes.fleet import router as fleet_router
from synapsis.routes.prms_dashboard import router as prms_dashboard_router

__all__ = [
    "health_router",
    "files_router",
    "sessions_router",
    "memories_router",
    "query_router",
    "export_router",
    "search_router",
    "agents_router",
    "dashboard_router",
    "workflows_router",
    "workflow_runs_router",
    "transcribe_router",
    "tts_router",
    "git_router",
    "agent_query_router",
    "skills_router",
    "fleet_router",
    "prms_dashboard_router",
]
