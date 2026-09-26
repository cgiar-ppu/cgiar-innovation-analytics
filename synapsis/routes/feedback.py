"""Feedback on answers and voice sessions (restricted test rounds).

- POST   /api/feedback                 own feedback: create or edit (one per user per item)
- GET    /api/feedback?session_id=…    own feedback for one chat (to show the current state)
- DELETE /api/feedback/{id}            withdraw own feedback
- GET    /api/admin/feedback           administrators: everyone's feedback, filters, ?format=csv

Why: after the 24-Sep World Bank/FCDO demo Jules asked for access "for testing
purposes to a restricted group of people and how to get their feedback", and
for "a feedback version of the voice function" that asks for a rating and one
improvement. Chat answers are rated thumbs up/down (+ optional comment and
"what should it have said?"); voice sessions are rated 1-5 with one suggested
improvement (``channel='voice'``, written by the voice guide's
``submit_feedback`` action or the end-of-call card).

Rules:
- Writes are owner-only: a chat must belong to the caller, a voice session must
  have been started by the caller. Anything else is a 404 (no existence leak).
- The question/answer text is stored only if the user ticks "share"; see
  ``synapsis.database.feedback`` for the privacy note.
- Nothing is forwarded (no Slack, no email). Feedback stays in this
  environment's database; the log line carries neither identities nor text.
- ``IA_FEEDBACK_ENABLED=false`` turns every endpoint into a 404 (the widget
  hides itself).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from synapsis.auth.middleware import get_current_user, resolve_role, resolve_user_id
from synapsis.auth.scoping import is_visible_to
from synapsis.database import feedback as store
from synapsis.database.sessions import get_session_owner
from synapsis.routes.usage import _environment_label

router = APIRouter(tags=["feedback"])
NO_STORE = {"Cache-Control": "no-store"}


def feedback_enabled() -> bool:
    return os.getenv("IA_FEEDBACK_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def require_enabled() -> None:
    if not feedback_enabled():
        raise HTTPException(404, "Feedback is not enabled in this environment")


def _clean(value: str) -> str:
    # Keep line breaks, drop other control characters.
    return "".join(ch for ch in value if ch in "\n\t" or ch >= " ").strip()


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["chat", "voice"] = "chat"
    session_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(default="", max_length=12)
    rating: int
    comment: str = Field(default="", max_length=2000)
    expected: str = Field(default="", max_length=4000)
    share_answer: bool = False
    # Picker state at rating time; used only when the chat turn predates the
    # server-side record of specialist/scope. Validated, never trusted blindly.
    persona: Optional[str] = Field(default=None, max_length=80)
    scope: Optional[dict] = None

    @field_validator("comment", "expected")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return _clean(value)


def _scope_text(scope: Optional[dict]) -> str:
    if not scope:
        return ""
    try:
        from synapsis.scope import normalize_scope, scope_is_empty
        normalized = normalize_scope(scope)
    except Exception:
        return ""
    if scope_is_empty(normalized):
        return ""
    return json.dumps(normalized, sort_keys=True)


def _persona_text(persona: Optional[str]) -> str:
    if not persona:
        return ""
    try:
        from synapsis.persona import normalize_persona
        return normalize_persona(persona)
    except Exception:
        return ""


async def _require_own_chat(session_id: str, user: dict) -> None:
    owner = await get_session_owner(session_id)
    if not is_visible_to(owner, resolve_user_id(user), resolve_role(user)):
        raise HTTPException(404, "Chat not found")


@router.post("/api/feedback")
async def save_feedback(body: FeedbackIn, user: dict = Depends(get_current_user)):
    require_enabled()
    user_id = resolve_user_id(user)
    role = resolve_role(user)
    common = {
        "user_id": user_id,
        "role": role,
        "cohort": await store.cohort_for(user_id),
        "app_version": os.getenv("GIT_SHA", "unknown"),
        "environment": _environment_label(),
    }
    if body.channel == "chat":
        match = store.ANSWER_ID.match(body.message_id)
        if not match:
            raise HTTPException(422, "message_id must identify a finished answer (r1, r2, …)")
        if body.rating not in (1, -1):
            raise HTTPException(422, "Chat answers are rated 1 (helpful) or -1 (not helpful)")
        await _require_own_chat(body.session_id, user)
        context = await store.answer_context(body.session_id, int(match.group(1)))
        if context is None:
            raise HTTPException(404, "Answer not found")
        saved = await store.upsert_feedback(
            **common,
            channel="chat",
            session_id=body.session_id,
            message_id=body.message_id,
            rating=body.rating,
            comment=body.comment,
            expected=body.expected,
            shared_question=context["question"][: store.MAX_SHARED_QUESTION] if body.share_answer else None,
            shared_answer=context["answer"][: store.MAX_SHARED_ANSWER] if body.share_answer else None,
            model=context["model"],
            persona=context["persona"] or _persona_text(body.persona),
            scope=_scope_text(context["scope"]) if context["scope"] is not None else _scope_text(body.scope),
        )
    else:
        try:
            request_id = str(UUID(body.session_id))
        except ValueError:
            raise HTTPException(422, "session_id must be the voice session id") from None
        if body.message_id:
            raise HTTPException(422, "Voice feedback has no message_id")
        if not 1 <= body.rating <= 5:
            raise HTTPException(422, "Voice sessions are rated from 1 to 5")
        if body.expected or body.share_answer:
            raise HTTPException(422, "Voice feedback takes a rating and one improvement only")
        if not await store.voice_session_exists(user_id, request_id):
            raise HTTPException(404, "Voice session not found")
        from synapsis.voice.config import model as voice_model
        saved = await store.upsert_feedback(
            **common,
            channel="voice",
            session_id=request_id,
            message_id="",
            rating=body.rating,
            comment=body.comment,
            model=voice_model(),
        )
    store.log_saved(body.channel, body.rating)
    return JSONResponse(saved, headers=NO_STORE)


@router.get("/api/feedback")
async def my_feedback(
    session_id: str = Query(min_length=1, max_length=100),
    channel: Literal["chat", "voice"] = "chat",
    user: dict = Depends(get_current_user),
):
    require_enabled()
    rows = await store.own_feedback(resolve_user_id(user), session_id, channel)
    return JSONResponse({"session_id": session_id, "feedback": rows}, headers=NO_STORE)


@router.delete("/api/feedback/{feedback_id}")
async def withdraw_feedback(feedback_id: int, user: dict = Depends(get_current_user)):
    require_enabled()
    if not await store.delete_own_feedback(resolve_user_id(user), feedback_id):
        raise HTTPException(404, "Feedback not found")
    return {"deleted": True}


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if resolve_role(user) != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@router.get("/api/admin/feedback")
async def admin_feedback(
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    days: Optional[int] = Query(None, ge=1, le=366),
    rating: Optional[Literal["positive", "negative", "neutral"]] = None,
    cohort: Optional[str] = Query(None, max_length=60),
    channel: Optional[Literal["chat", "voice"]] = None,
    limit: int = Query(1000, ge=1, le=5000),
    format: Literal["json", "csv"] = "json",
    user: dict = Depends(_require_admin),
):
    """Everyone's feedback (admin only). ``from``/``to`` are UTC dates
    (inclusive); ``days`` is a shortcut for the last N days. ``cohort=__none__``
    selects users without a cohort (e.g. CGIAR staff on SSO)."""
    require_enabled()
    if days and not date_from:
        start = datetime.now(timezone.utc).timestamp() - (days - 1) * 86400
        date_from = datetime.fromtimestamp(start, tz=timezone.utc).date()
    result = await store.list_feedback(
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        rating=rating, cohort=cohort, channel=channel, limit=limit,
    )
    env = _environment_label()
    if format == "csv":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return Response(
            content="﻿" + store.to_csv(result["items"]),
            media_type="text/csv; charset=utf-8",
            headers={**NO_STORE, "Content-Disposition": f'attachment; filename="ia-feedback-{env}-{stamp}.csv"'},
        )
    return JSONResponse({
        "environment": env,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filters": {"from": date_from.isoformat() if date_from else None,
                    "to": date_to.isoformat() if date_to else None,
                    "rating": rating, "cohort": cohort, "channel": channel},
        **result,
    }, headers=NO_STORE)
