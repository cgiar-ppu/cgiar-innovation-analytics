"""
Health, activity, and configuration endpoints.

- GET /api/health   — Basic health check
- GET /api/activity — Activity metrics for cleanup Lambda
- GET /api/config   — Full app configuration
"""

import os

from fastapi import APIRouter

from synapsis.config import MODEL, FALLBACK_MODEL, MAX_TURNS, WORKSPACE, AUTH_METHOD, IS_MACOS, SYNAPSIS_PLATFORM, APP_VERSION
from synapsis.agents import SUBAGENTS
from synapsis.constants import MEMORY_CATEGORIES

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    """Basic health check returning model, workspace, and auth info."""
    return {
        "status": "ok",
        "model": MODEL,
        "workspace": str(WORKSPACE),
        "auth_method": AUTH_METHOD,
        "version": APP_VERSION,
    }


@router.get("/activity")
async def activity():
    """Report container activity for cleanup Lambda.

    The cleanup Lambda checks this endpoint before terminating idle containers.
    """
    # Import at call time to avoid circular imports with server module
    from synapsis.server import get_activity_stats
    stats = get_activity_stats()
    return stats


@router.get("/config")
async def get_config():
    """Return full app configuration for the frontend."""
    return {
        "model": MODEL,
        "fallback_model": FALLBACK_MODEL,
        "max_turns": MAX_TURNS,
        "auth_method": AUTH_METHOD,
        "version": APP_VERSION,
        "agent_type": "synapsis_analytics",
        "personas": list(SUBAGENTS.keys()),
        "memory_categories": MEMORY_CATEGORIES,
        "vnc_available": not IS_MACOS and os.environ.get("DISPLAY") is not None,
        "vnc_port": 6080,
        "platform": SYNAPSIS_PLATFORM,
    }
