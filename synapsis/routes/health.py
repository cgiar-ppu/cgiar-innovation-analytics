"""
Health, activity, and configuration endpoints.

- GET /api/health   — Basic health check. Anonymous callers (load balancer,
                       deploy scripts) get status, git_sha, version and the
                       default model only; the model list, workspace path and
                       auth method are returned to administrators only.
- GET /api/activity — Connection/session activity counters (signed-in users
                       only; nothing public reads it in this deployment).
- GET /api/config   — Full app configuration (model list is role-aware:
                       admins get the stage list, everyone else the
                       researcher list, anonymous callers only the default)
                       plus the in-app "reach out if in doubt" contacts.
"""

import os

from fastapi import APIRouter, Depends

from synapsis.config import (
    MODEL,
    MAX_TURNS,
    WORKSPACE,
    AUTH_METHOD,
    SYNAPSIS_PLATFORM,
    APP_VERSION,
    SELF_SIGNUP_ENABLED,
    SIGNUP_ALLOWED_DOMAINS,
    SSO_ENABLED,
    PASSWORD_LOGIN_ENABLED,
    INVITED_LOGIN_ENABLED,
)
from synapsis.agents import SUBAGENTS
from synapsis.auth.middleware import get_current_user, get_optional_user, resolve_role
from synapsis.runtime_policy import (
    allowed_models_for_role,
    fallback_model_for_role,
    policy_summary,
    selectable_models_for_role,
)

router = APIRouter(prefix="/api", tags=["health"])

# In-app "reach out if in doubt" contacts (guardrails, Jules call 2026-07-07).
# Served by /api/config so the address can change per environment without a
# frontend rebuild. The technical default is the CGIAR mailbox because the
# previous synapsis-analytics.com address bounced for an external user
# (18 Sep 2026). PENDING CONFIRMATION by Jose Luis Berenguer.
_DEFAULT_CONTACTS = (
    ("IA_CONTACT_SCOPE_NAME", "Marc Schut", "IA_CONTACT_SCOPE_EMAIL", "marc.schut@cgiar.org", "scope & use"),
    ("IA_CONTACT_TECHNICAL_NAME", "Jose Luis Berenguer", "IA_CONTACT_TECHNICAL_EMAIL", "J.Berenguer@cgiar.org", "technical"),
)


def guardrail_contacts() -> list[dict]:
    """Contacts shown in the disclaimer modal and footer.

    Each entry is configurable through its ``IA_CONTACT_*`` variables; an
    empty email variable removes that contact.
    """
    contacts = []
    for name_var, name_default, email_var, email_default, remit in _DEFAULT_CONTACTS:
        email = os.getenv(email_var, email_default).strip()
        if not email:
            continue
        name = os.getenv(name_var, name_default).strip() or email
        contacts.append({"name": name, "email": email, "remit": remit})
    return contacts


@router.get("/health")
async def health(user=Depends(get_optional_user)):
    """Basic health check.

    ``status`` and ``git_sha`` are what the deploy/release scripts read.
    Anonymous callers do not get the model list, workspace path or auth
    method (they revealed which premium models a deployment offers); only
    administrators do.
    """
    body = {
        "status": "ok",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "model": MODEL,
        "version": APP_VERSION,
    }
    if user and resolve_role(user) == "admin":
        body.update({
            "workspace": str(WORKSPACE),
            "auth_method": AUTH_METHOD,
            "available_models": allowed_models_for_role("admin"),
        })
    return body


@router.get("/activity")
async def activity(_user=Depends(get_current_user)):
    """Report connection/session activity counters (signed-in users only).

    Formerly anonymous for the Synapsis multi-tenant cleanup Lambda
    (``infra/template.yaml``), which this deployment does not run.
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
        "platform": SYNAPSIS_PLATFORM,
        # "Reach out if in doubt" contacts for the disclaimer modal/footer.
        "contacts": guardrail_contacts(),
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
