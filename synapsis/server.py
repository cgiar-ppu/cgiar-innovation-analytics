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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from synapsis.config import logger
from synapsis.security_headers import SecurityHeadersMiddleware, cors_settings
from synapsis.database import init_db, close_db
from synapsis.workflow_db import init_workflow_db, close_workflow_db
from synapsis.database.fleet_schema import init_fleet_db
from synapsis.database.fleet_connection import close_fleet_db
from synapsis.routes import (
    health_router,
    files_router,
    sessions_router,
    query_router,
    export_router,
    search_router,
    agents_router,
    transcribe_router,
    tts_router,
    prms_dashboard_router,
    scope_router,
)
from synapsis.auth.routes import router as auth_router
from synapsis.auth.sso_routes import router as sso_router
from synapsis.auth.invited_routes import router as invited_router
from synapsis.auth.log_redaction import install_auth_url_redaction
from synapsis.auth.sso_provider import validate_settings as validate_sso_settings
from synapsis.routes.voice import router as voice_router
from synapsis.voice import sessions as voice_sessions
from synapsis.websocket import ws_chat, get_activity_stats, cleanup_session_client


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# FastAPI's default /docs, /redoc and /openapi.json are disabled; guarded
# versions are registered below (QA-4 D15).
app = FastAPI(title="CGIAR Innovation Analytics Platform", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None)

# -- HTTP hardening (review 2026-09-23 L1-07/L1-08/L4-12) --
# Order: the last middleware added is the outermost. CORS is outermost so
# preflights are answered first; security headers wrap every HTTP response
# (including errors and the SPA); GZip compresses the ~2 MB of JS/CSS.
# CORS used to be "*" + credentials in every env; it is now the env's own
# origin (CORS_ORIGINS, else IA_SSO_ORIGIN) — see synapsis/security_headers.py.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, **cors_settings())

# -- Register route routers --
app.include_router(auth_router)
validate_sso_settings()
install_auth_url_redaction()
app.include_router(sso_router)
app.include_router(invited_router)
app.include_router(voice_router)
app.include_router(health_router)
from synapsis.routes.usage import router as usage_router  # noqa: E402  (Lane D: admin usage summary)
app.include_router(usage_router)
from synapsis.routes.feedback import router as feedback_router  # noqa: E402  (Lane H: answer/voice feedback)
app.include_router(feedback_router)
app.include_router(files_router)
app.include_router(sessions_router)
app.include_router(query_router)
app.include_router(export_router)
app.include_router(search_router)
app.include_router(agents_router)
app.include_router(transcribe_router)
app.include_router(tts_router)
app.include_router(prms_dashboard_router)
app.include_router(scope_router)
# Deliberately NOT registered (Synapsis-agent leftovers, review 2026-09-23
# L7-05/L1-04/L1-06/L6-07): memories, workflows, workflow_runs, workflow_logs,
# git, agent_query, skills, fleet, images, dashboard (/api/dashboard/stats).
# They were global across users and, for agent_query/workflows, replaced the
# IA system prompt. tests/test_leftover_routes.py pins their absence.

# -- API documentation (QA-4 D15) --
# The schema and the Swagger/ReDoc pages are API-surface disclosure: every
# operation is still gated, but an anonymous visitor on a deployed stage has
# no business listing them. They stay available:
#   * in local development (IA_AUTH_DISABLED=true);
#   * to in-container callers talking to the app directly on the loopback
#     interface WITHOUT an X-Forwarded-For header (release-smoke.py and the
#     DEV QA smoke walk /openapi.json from inside the container; every request
#     through the load balancer carries X-Forwarded-For);
#   * /openapi.json to administrators (Bearer token).
# Anyone else gets a plain 404 (the SPA catch-all must not answer these).
from fastapi import Depends  # noqa: E402
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html  # noqa: E402

from synapsis.auth import middleware as _auth_mw  # noqa: E402

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def api_docs_allowed(request: Request, user: dict | None, *, admin_ok: bool = True) -> bool:
    """Whether this caller may read the API schema/docs (see above)."""
    if _auth_mw.AUTH_DISABLED:
        return True
    host = request.client.host if request.client else ""
    if host in _LOOPBACK and "x-forwarded-for" not in request.headers:
        return True
    return admin_ok and bool(user) and _auth_mw.resolve_role(user) == "admin"


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request, user=Depends(_auth_mw.get_optional_user)):
    if not api_docs_allowed(request, user):
        return _not_found()
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
async def swagger_docs(request: Request, user=Depends(_auth_mw.get_optional_user)):
    # The page fetches /openapi.json without a token, so it only works where
    # the schema is open without one (local / in-container).
    if not api_docs_allowed(request, user, admin_ok=False):
        return _not_found()
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - API")


@app.get("/redoc", include_in_schema=False)
async def redoc_docs(request: Request, user=Depends(_auth_mw.get_optional_user)):
    if not api_docs_allowed(request, user, admin_ok=False):
        return _not_found()
    return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - API")


# -- Register WebSocket endpoints --
# /ws/chat is the ONLY WebSocket. The Synapsis-era /ws/agent, /ws/workflow and
# /ws/fleet sockets accepted anonymous handshakes and drove a shell-capable
# agent (review 2026-09-23, P0-1); they were removed, not just guarded.
# tests/test_ws_auth.py pins this set.
app.websocket("/ws/chat")(ws_chat)


# -- Startup event: initialize database --
@app.on_event("startup")
async def on_startup():
    """Initialize the SQLite databases and background tasks on app startup."""
    await init_db()
    await voice_sessions.startup()
    await init_workflow_db()
    await init_fleet_db()
    logger.info("Databases initialized (chat, workflow, fleet)")

    # Ensure analytical indexes exist on the PRMS `result` table. The PRMS DB is
    # periodically replaced with a fresh artifact that ships without indexes, so
    # we (re)create them at every startup via CREATE INDEX IF NOT EXISTS. Mirrors
    # the PRMS_DB_PATH resolution used by prms_query.py / prms_dashboard.py.
    from synapsis.db_init import ensure_result_indexes
    from synapsis.prms_snapshot import resolve_db_path as _resolve_prms_db_path
    _prms_db_path = _resolve_prms_db_path()
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
    await voice_sessions.shutdown()
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


#: Prefixes that belong to the backend, never to the SPA. An unknown path
#: under them is a clean JSON 404 (removed Synapsis routes must not "succeed"
#: with index.html, and API clients must not parse HTML).
_BACKEND_PREFIXES = ("api", "ws")


@app.get("/{full_path:path}")
async def spa_catch_all(request: Request, full_path: str):
    """Serve index.html for all frontend routes (SPA catch-all)."""
    first = full_path.split("/", 1)[0]
    if first in _BACKEND_PREFIXES:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    # If the path points to an actual file INSIDE static/, serve it directly.
    # Resolve first: uvicorn does not normalise ``..`` segments, so a raw
    # request for ``/../<file>`` would otherwise escape static/ (found
    # 2026-09-26; the DEV nginx front rejects such paths, this is the app-side
    # guard).
    static_root = _static_dir.resolve()
    candidate = (_static_dir / full_path).resolve()
    if candidate.is_relative_to(static_root) and candidate.is_file():
        return FileResponse(str(candidate))
    if not _index_html.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
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
