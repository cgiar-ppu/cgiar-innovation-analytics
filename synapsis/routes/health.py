"""
Health, activity, and configuration endpoints.

- GET /api/health   — Basic health check
- GET /api/activity — Activity metrics for cleanup Lambda
- GET /api/config   — Full app configuration (model list is role-aware:
                       admins get the stage list, everyone else the
                       researcher list, anonymous callers only the default)
"""

import os

from fastapi import APIRouter, Depends

from synapsis.config import (
    MODEL,
    MAX_TURNS,
    WORKSPACE,
    AUTH_METHOD,
    IS_MACOS,
    SYNAPSIS_PLATFORM,
    APP_VERSION,
    AVAILABLE_MODELS,
    SELF_SIGNUP_ENABLED,
    SIGNUP_ALLOWED_DOMAINS,
    SSO_ENABLED,
    PASSWORD_LOGIN_ENABLED,
    INVITED_LOGIN_ENABLED,
)
from synapsis.agents import SUBAGENTS
from synapsis.auth.middleware import get_optional_user, resolve_role
from synapsis.constants import MEMORY_CATEGORIES
from synapsis.runtime_policy import (
    allowed_models_for_role,
    fallback_model_for_role,
    policy_summary,
    selectable_models_for_role,
)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    """Basic health check returning model, workspace, and auth info."""
    return {
        "status": "ok",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
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
async def get_config(user=Depends(get_optional_user)):
    """Return app configuration for the frontend.

    ``selectable_models`` / ``available_models`` are the models the *caller*
    may use (same shape as before): with a valid token, the role's list
    (admins: every model this deployment exposes; researchers/invited: the
    researcher list, Sonnet 5 by default); without a token (login screen),
    only the default model. ``model_policy`` carries the caller's ceilings so
    the UI can hide the cost pill for non-admins. An invalid token is treated
    as anonymous, never as an error, because the login screen calls this too.
    """
    role = resolve_role(user) if user else None
    return {
        "model": MODEL,
        "fallback_model": fallback_model_for_role(role) if role else "",
        "selectable_models": selectable_models_for_role(role),
        "available_models": allowed_models_for_role(role),
        "model_policy": policy_summary(role),
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
        "sso_enabled": SSO_ENABLED,
        "password_login_enabled": PASSWORD_LOGIN_ENABLED,
        "invited_login_enabled": INVITED_LOGIN_ENABLED,
    }
