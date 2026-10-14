"""
Admin usage summary — cost and activity per day, role and model.

- GET /api/admin/usage?days=N  (admin only; N = 1..90, default 14)
  also carries ``test_budget`` (SYN-2306): budget, spent, pct, window, state,
  crossed alert thresholds - what an external monitor polls.
- GET /api/admin/engagement?days=N      (admin only) first-party usage events
  (SYN-2305): questions, clicks, session length per day / user / cohort.
- GET /api/admin/engagement.csv?days=N  (admin only) one row per day x user.

Answers "how much does this environment cost, and who/what drives it?" for
Jose and Jules. Each environment (DEV/TST/PRD) has its own chat database, so
calling this on each host gives the per-environment split. Only aggregate
counts are returned — never user identities or message content. The
engagement read-outs list accounts by a keyed pseudonym (``user_key``) with
role and test cohort, never by e-mail or name.
"""

import csv
import io
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import synapsis.config as _config
from synapsis.auth.middleware import get_current_user, resolve_role
from synapsis.database.usage import usage_summary
from synapsis.runtime_policy import policy_summary, test_budget_status

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
        "test_budget": await test_budget_status(),
        **summary,
    }


TRACKING_NOTE = (
    "First-party, cookieless event log modelled on Umami's open-source event "
    "schema (page views, clicks on tagged elements, 30-s heartbeats for session "
    "length). Same origin only: no cookies, no third-party script. Questions "
    "and cost come from the per-question ledger. Accounts are shown as keyed "
    "pseudonyms (user_key) with role and test cohort."
)


@router.get("/engagement")
async def admin_engagement(days: int = Query(14, ge=1, le=90), user: dict = Depends(_require_admin)):
    from synapsis.database.telemetry import engagement_summary

    summary = await engagement_summary(days)
    return {
        "environment": _environment_label(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tracking": TRACKING_NOTE,
        "telemetry_enabled": bool(_config.TELEMETRY_ENABLED),
        **summary,
    }


@router.get("/engagement.csv")
async def admin_engagement_csv(days: int = Query(14, ge=1, le=90), user: dict = Depends(_require_admin)):
    from synapsis.database.telemetry import CSV_COLUMNS, engagement_csv_rows

    env = _environment_label()
    rows = await engagement_csv_rows(days)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({"environment": env, **row})
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ia-engagement-{env}-{days}d-{stamp}.csv"'},
    )
