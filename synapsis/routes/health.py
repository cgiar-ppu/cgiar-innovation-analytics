"""
Health, activity, and configuration endpoints.

- GET /api/health   — Basic health check
- GET /api/activity — Activity metrics for cleanup Lambda
- GET /api/config   — Full app configuration
"""

import os

from fastapi import APIRouter

from synapsis.config import (
    MODEL,
    FALLBACK_MODEL,
    MAX_TURNS,
    WORKSPACE,
    AUTH_METHOD,
    IS_MACOS,
    SYNAPSIS_PLATFORM,
    APP_VERSION,
    AVAILABLE_MODELS,
    SELECTABLE_MODELS_FILTERED,
    SELF_SIGNUP_ENABLED,
    SIGNUP_ALLOWED_DOMAINS,
)
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
        "available_models": AVAILABLE_MODELS,
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
        "selectable_models": SELECTABLE_MODELS_FILTERED,
        "available_models": AVAILABLE_MODELS,
        "max_turns": MAX_TURNS,
        "auth_method": AUTH_METHOD,
        "version": APP_VERSION,
        "agent_type": "synapsis_analytics",
        "personas": list(SUBAGENTS.keys()),
        "memory_categories": MEMORY_CATEGORIES,
        "vnc_available": not IS_MACOS and os.environ.get("DISPLAY") is not None,
        "vnc_port": 6080,
        "platform": SYNAPSIS_PLATFORM,
        # Interim self-signup (no email confirmation) — the frontend only
        # shows the "Create account" option when this is true. Flag-gated
        # server-side (IA_SELF_SIGNUP); defaults false so prod-lineage
        # deployments stay closed.
        "self_signup": SELF_SIGNUP_ENABLED,
        # Email domains self-signup accepts (IA_SIGNUP_ALLOWED_DOMAINS).
        # Empty list = no domain restriction. The login screen shows this as
        # a hint so users see the rule before submitting.
        "signup_allowed_domains": SIGNUP_ALLOWED_DOMAINS,
    }
