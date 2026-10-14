"""First-party usage events: ``POST /api/telemetry`` (SYN-2305, 2026-10-14).

The SPA's telemetry module (``frontend/src/lib/telemetry.ts``) posts batches
of up to 50 events. Two same-origin transports are accepted:

* ``fetch(..., {keepalive: true})`` with the usual ``Authorization: Bearer``
  header (timer flushes);
* ``navigator.sendBeacon`` on page hide. A beacon cannot carry headers, so the
  app token travels in the JSON body as ``token`` and is verified exactly like
  the header (signature, expiry, revocation). It is never stored or logged.

Body: ``{"events": [{"id", "type", "ts", "visit_id", "path", "name",
"chat_session_id", "value"}], "token"?: "..."}``. Unknown event types and
malformed rows are dropped (see ``synapsis.database.telemetry.clean_event``).

Answers ``204`` (nothing to read back), ``401`` without a valid identity,
``413`` for an oversized body, ``404`` when ``IA_TELEMETRY_ENABLED=false`` (the
client then stops sending). Ingestion never blocks the UI: errors are logged
and swallowed after authentication.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

import synapsis.config as _config
from synapsis.auth.middleware import resolve_role, resolve_user_id
from synapsis.auth.tokens import verify_token
from synapsis.config import logger

router = APIRouter(prefix="/api", tags=["telemetry"])

MAX_BODY_BYTES = 64 * 1024
_recent: dict[str, deque] = {}


def _identity(request: Request, body_token: Optional[str]) -> Optional[dict]:
    import synapsis.auth.middleware as _mw

    if _mw.AUTH_DISABLED:
        return dict(_mw._DEV_USER)
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token and isinstance(body_token, str):
        token = body_token.strip()
    if not token:
        return None
    return verify_token(token)


def _allow(user_id: str, n: int, now: float) -> int:
    """How many of ``n`` events this user may still send this minute."""
    cap = max(0, int(_config.TELEMETRY_MAX_EVENTS_PER_MINUTE))
    q = _recent.setdefault(user_id, deque())
    while q and now - q[0] > 60:
        q.popleft()
    room = max(0, cap - len(q))
    take = min(n, room)
    q.extend([now] * take)
    if len(_recent) > 5000:  # forget idle users
        for uid in [u for u, d in _recent.items() if not d or now - d[-1] > 60][:1000]:
            _recent.pop(uid, None)
    return take


@router.post("/telemetry", status_code=204)
async def post_telemetry(request: Request) -> Response:
    if not _config.TELEMETRY_ENABLED:
        raise HTTPException(status_code=404, detail="Telemetry is disabled")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object")

    user = _identity(request, payload.get("token"))
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})

    from synapsis.database.telemetry import MAX_BATCH, clean_event, cohort_for, record_events
    from synapsis.routes.usage import _environment_label

    events = payload.get("events")
    if not isinstance(events, list):
        return Response(status_code=204)
    now = time.time()
    cleaned = [e for e in (clean_event(r, now) for r in events[:MAX_BATCH]) if e]
    user_id = resolve_user_id(user)
    allowed = _allow(user_id, len(cleaned), now)
    try:
        await record_events(
            cleaned[:allowed], user_id=user_id, role=resolve_role(user),
            env=_environment_label(), cohort=await cohort_for(user_id),
        )
    except Exception:
        logger.warning("Telemetry batch could not be stored", exc_info=True)
    return Response(status_code=204)
