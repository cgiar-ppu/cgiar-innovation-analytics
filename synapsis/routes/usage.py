"""
Admin usage summary — cost and activity per day, role and model.

- GET /api/admin/usage?days=N  (admin only; N = 1..90, default 14)

Answers "how much does this environment cost, and who/what drives it?" for
Jose and Jules. Each environment (DEV/TST/PRD) has its own chat database, so
calling this on each host gives the per-environment split. Only aggregate
counts are returned — never user identities or message content.
"""

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query

import synapsis.config as _config
from synapsis.auth.middleware import get_current_user, resolve_role
from synapsis.database.usage import usage_summary
from synapsis.runtime_policy import policy_summary

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if resolve_role(user) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _environment_label() -> str:
    if _config.ENVIRONMENT_LABEL:
        return _config.ENVIRONMENT_LABEL
    host = (urlparse(_config.SSO_ORIGIN).hostname or "") if _config.SSO_ORIGIN else ""
    if host:
        if "-dev" in host:
            return "dev"
        if "-test" in host or "-tst" in host or "staging" in host:
            return "test"
        return "prod"
    return "local"


@router.get("/usage")
async def admin_usage(days: int = Query(14, ge=1, le=90), user: dict = Depends(_require_admin)):
    """Per-day turns, sessions, distinct users and USD cost by role and model,
    plus voice sessions/minutes. See ``synapsis.database.usage.usage_summary``.
    """
    summary = await usage_summary(days)
    return {
        "environment": _environment_label(),
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "USD",
        "cost_basis": (
            "Model cost as reported by the Claude Agent SDK per question (list "
            "prices). Days before 'ledger_since' are estimated from chat history. "
            "Voice is reported in minutes, not USD. Hosting is not included."
        ),
        "policy": {
            "researcher": policy_summary("researcher"),
            "admin": policy_summary("admin"),
        },
        **summary,
    }
