"""
Synapsis server assembly — FastAPI app creation, startup, and static files.

This is the central module that:
1. Creates the FastAPI app instance
2. Registers all route routers
3. Registers the WebSocket endpoint
4. Initializes the database on startup
5. Mounts static files for the SPA frontend
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from synapsis.config import logger
from synapsis.database import init_db, close_db
from synapsis.workflow_db import init_workflow_db, close_workflow_db
from synapsis.database.fleet_schema import init_fleet_db
from synapsis.database.fleet_connection import close_fleet_db
from synapsis.routes import (
    health_router,
    files_router,
    sessions_router,
    memories_router,
    query_router,
    export_router,
    search_router,
    agents_router,
    dashboard_router,
    workflows_router,
    workflow_runs_router,
    transcribe_router,
    tts_router,
    git_router,
    agent_query_router,
    skills_router,
    fleet_router,
    prms_dashboard_router,
    images_router,
    scope_router,
)
from synapsis.auth.routes import router as auth_router
from synapsis.websocket import ws_chat, get_activity_stats, cleanup_session_client
from synapsis.workflow_ws import ws_workflow
from synapsis.agent_ws import ws_agent
from synapsis.fleet_ws import ws_fleet


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="CGIAR Innovation Analytics Platform", version="0.1.0")

# -- CORS middleware for external mini-app integration --
import os as _os
_cors_origins = _os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Register route routers --
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(files_router)
app.include_router(sessions_router)
app.include_router(memories_router)
app.include_router(query_router)
app.include_router(export_router)
app.include_router(search_router)
app.include_router(agents_router)
app.include_router(dashboard_router)
app.include_router(workflows_router)
app.include_router(workflow_runs_router)
app.include_router(transcribe_router)
app.include_router(tts_router)
app.include_router(git_router)
app.include_router(agent_query_router)
app.include_router(skills_router)
app.include_router(fleet_router)
app.include_router(prms_dashboard_router)
app.include_router(images_router)
app.include_router(scope_router)

# -- Register WebSocket endpoints --
app.websocket("/ws/chat")(ws_chat)
app.add_api_websocket_route("/ws/workflow/{workflow_id}", ws_workflow)
app.add_api_websocket_route("/ws/agent/{agent_id}", ws_agent)
app.add_api_websocket_route("/ws/fleet/{fleet_id}", ws_fleet)


# -- Startup event: initialize database --
@app.on_event("startup")
async def on_startup():
    """Initialize the SQLite databases and background tasks on app startup."""
    await init_db()
    await init_workflow_db()
    await init_fleet_db()
    logger.info("Databases initialized (chat, workflow, fleet)")

    # Ensure analytical indexes exist on the PRMS `result` table. The PRMS DB is
    # periodically replaced with a fresh artifact that ships without indexes, so
    # we (re)create them at every startup via CREATE INDEX IF NOT EXISTS. Mirrors
    # the PRMS_DB_PATH resolution used by prms_query.py / prms_dashboard.py.
    from synapsis.db_init import ensure_result_indexes
    _prms_db_path = _os.getenv(
        "PRMS_DB_PATH",
        "/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite",
    )
    ensure_result_indexes(_prms_db_path)
    logger.info("PRMS result-table indexes ensured (%s)", _prms_db_path)

    # Start the background idle session reaper
    from synapsis.session import session_manager as _sm
    _sm.start_reaper()
    logger.info("Idle session reaper started")


@app.on_event("shutdown")
async def on_shutdown():
    """Cancel running pipelines and close shared database connections on app shutdown."""
    from synapsis.workflow_run_manager import run_manager
    await run_manager.shutdown()
    logger.info("Workflow run manager shut down")
    from synapsis.chat_run_manager import chat_run_manager
    await chat_run_manager.shutdown()
    from synapsis.session import session_manager as _sm
    await _sm.stop_reaper()
    await close_db()
    await close_workflow_db()
    await close_fleet_db()
    from synapsis.services.fleet_manager import fleet_manager
    await fleet_manager.shutdown()
    logger.info("Database connections closed, fleet manager shut down")


# -- noVNC static files (served same-origin to avoid cross-origin ES module issues in iframes) --
import os
_novnc_dir = "/usr/share/novnc"
if os.path.isdir(_novnc_dir):
    app.mount("/vnc", StaticFiles(directory=_novnc_dir), name="novnc")

# -- Static assets (JS, CSS, images) --
_static_dir = Path("static")
if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")


# -- SPA catch-all: serve index.html for any non-API, non-asset path --
# This enables client-side routing (React Router) for paths like /chat,
# /agents, /workflows, etc.
_index_html = _static_dir / "index.html"


@app.get("/{full_path:path}")
async def spa_catch_all(request: Request, full_path: str):
    """Serve index.html for all frontend routes (SPA catch-all)."""
    # If the path points to an actual file in static/, serve it directly
    candidate = _static_dir / full_path
    if candidate.is_file():
        return FileResponse(str(candidate))
    # Otherwise serve the SPA entry point — with no-cache so proxies always
    # fetch the latest index.html (asset filenames are content-hashed, so
    # they can be cached indefinitely, but index.html must stay fresh)
    return FileResponse(
        str(_index_html),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# Re-export functions used by route modules (avoids circular imports)
# ---------------------------------------------------------------------------
# These are imported by routes/health.py and routes/sessions.py

__all__ = ["app", "get_activity_stats", "cleanup_session_client"]
