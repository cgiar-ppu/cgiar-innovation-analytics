"""Feedback on answers and voice sessions (restricted test rounds).

- POST   /api/feedback                 own feedback: create or edit (one per user per item)
- GET    /api/feedback?session_id=…    own feedback for one chat (to show the current state)
- DELETE /api/feedback/{id}            withdraw own feedback
- POST   /api/feedback/general         "Give feedback" form on every page (multipart, optional screenshot)
- GET    /api/admin/feedback           administrators: everyone's feedback, filters, ?format=csv|zip
- GET    /api/admin/feedback/{id}/attachment   administrators: the screenshot of one submission

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
  hides itself; ``GET /api/config`` reports ``feedback_enabled``).

General feedback (MVP test release item 1, requirements of 9 Oct 2026: "attach
screenshots; flag when they are stuck, when a result looks wrong, or when the
tool is inappropriate/inaccurate"): a category, free text, an optional PNG/JPEG
screenshot (max 5 MB, checked by file signature, stored as a file next to the
database, never inside the row) and context the server derives itself
(role, cohort, environment, app version; the chat id is kept only if the chat
belongs to the caller). A user can send at most ``GENERAL_PER_HOUR``
submissions per hour.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from synapsis.auth.middleware import get_current_user, resolve_role, resolve_user_id
from synapsis.auth.scoping import is_visible_to
from synapsis.database import feedback as store
from synapsis.database.sessions import get_session_owner
from synapsis.routes.usage import _environment_label

router = APIRouter(tags=["feedback"])
NO_STORE = {"Cache-Control": "no-store"}


#: Largest request body accepted by ``POST /api/feedback/general``: the 5 MB
#: screenshot plus the form fields and multipart framing.
MAX_GENERAL_REQUEST_BYTES = store.MAX_ATTACHMENT_BYTES + 256 * 1024


class FeedbackUploadLimitMiddleware:
    """Refuse an oversized feedback upload from its Content-Length, BEFORE the
    multipart body is spooled to disk (the per-file 5 MB check in the route
    runs only after Starlette has written the whole part to a temp file).

    Pure ASGI; touches only ``POST /api/feedback/general``. A body sent without
    a Content-Length (chunked) is still bounded by the route's own check.
    """

    PATH = "/api/feedback/general"

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("method") == "POST" and scope.get("path") == self.PATH:
            declared = dict(scope.get("headers") or []).get(b"content-length", b"")
            if declared.isdigit() and int(declared) > MAX_GENERAL_REQUEST_BYTES:
                from starlette.responses import JSONResponse
                await JSONResponse(
                    {"detail": "The screenshot must be 5 MB or smaller"}, status_code=413,
                    headers={"Connection": "close"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def feedback_enabled() -> bool:
    return os.getenv("IA_FEEDBACK_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def require_enabled() -> None:
    if not feedback_enabled():
        raise HTTPException(404, "Feedback is not enabled in this environment")


def _clean(value: str) -> str:
    # Keep line breaks, drop other control characters.
    return "".join(ch for ch in value if ch in "\n\t" or ch >= " ").strip()


GENERAL_PER_HOUR = 30
MAX_GENERAL_COMMENT = 4000
_PAGE = re.compile(r"^/[A-Za-z0-9/_\-.~%]{0,199}$")


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["chat", "voice", "general"] = "chat"
    session_id: str = Field(default="", max_length=100)
    message_id: str = Field(default="", max_length=12)
    rating: int = 0
    comment: str = Field(default="", max_length=MAX_GENERAL_COMMENT)
    expected: str = Field(default="", max_length=4000)
    share_answer: bool = False
    # channel='general' only (the "Give feedback" form; JSON = no screenshot).
    category: Optional[Literal["stuck", "wrong_result", "inappropriate_inaccurate", "other"]] = None
    page: str = Field(default="", max_length=300)
    chat_id: str = Field(default="", max_length=100)
    answer_id: str = Field(default="", max_length=12)

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


async def _require_own_chat(session_id: str, user: dict) -> None:
    owner = await get_session_owner(session_id)
    if not is_visible_to(owner, resolve_user_id(user), resolve_role(user)):
        raise HTTPException(404, "Chat not found")


async def _common(user: dict) -> dict:
    user_id = resolve_user_id(user)
    return {
        "user_id": user_id,
        "role": resolve_role(user),
        "cohort": await store.cohort_for(user_id),
        "app_version": os.getenv("GIT_SHA", "unknown"),
        "environment": _environment_label(),
    }


def _clean_page(page: str) -> str:
    """The app route the form was sent from (path only; anything else is dropped)."""
    page = (page or "").split("?", 1)[0].split("#", 1)[0].strip()
    return page if _PAGE.match(page) else ""


async def _save_general(
    user: dict,
    *,
    category: str,
    comment: str,
    page: str,
    chat_id: str,
    answer_id: str,
    attachment_path: str = "",
) -> dict:
    """Store a general feedback row with server-derived context."""
    common = await _common(user)
    since = time.time() - 3600
    if await store.recent_general_count(common["user_id"], since) >= GENERAL_PER_HOUR:
        raise HTTPException(429, "Thanks - you have sent a lot of feedback in the last hour. Please try again later.")
    chat_id = (chat_id or "").strip()
    answer_id = (answer_id or "").strip()
    context: dict = {"model": "", "persona": "", "scope": ""}
    if chat_id:
        owner = await get_session_owner(chat_id)
        # A foreign or unknown chat id is dropped, never stored (no existence leak).
        if owner is None or not is_visible_to(owner, common["user_id"], common["role"]):
            chat_id, answer_id = "", ""
    else:
        answer_id = ""
    match = store.ANSWER_ID.match(answer_id) if answer_id else None
    if answer_id and not match:
        answer_id = ""
    if chat_id and match:
        found = await store.answer_context(chat_id, int(match.group(1)))
        if found is None:
            answer_id = ""
        else:
            context = {"model": found["model"], "persona": found["persona"], "scope": _scope_text(found["scope"])}
    saved = await store.insert_general_feedback(
        **common,
        category=category,
        comment=comment,
        page=_clean_page(page),
        chat_id=chat_id,
        answer_id=answer_id,
        attachment_path=attachment_path,
        **context,
    )
    store.log_saved("general", 0, category, bool(attachment_path))
    return saved


@router.post("/api/feedback")
async def save_feedback(body: FeedbackIn, user: dict = Depends(get_current_user)):
    require_enabled()
    if body.channel == "general":
        if body.category is None:
            raise HTTPException(422, "General feedback needs a category")
        if body.session_id or body.message_id or body.rating or body.expected or body.share_answer:
            raise HTTPException(422, "General feedback takes a category, a comment and page context only")
        if not body.comment:
            raise HTTPException(422, "Please describe what happened")
        saved = await _save_general(user, category=body.category, comment=body.comment, page=body.page,
                                    chat_id=body.chat_id, answer_id=body.answer_id)
        return JSONResponse(saved, headers=NO_STORE)
    if body.category is not None or body.page or body.chat_id or body.answer_id:
        raise HTTPException(422, "category/page/chat_id/answer_id are for general feedback only")
    if not body.session_id:
        raise HTTPException(422, "session_id is required")
    if len(body.comment) > 2000:
        raise HTTPException(422, "Comment is limited to 2,000 characters")
    common = await _common(user)
    user_id = common["user_id"]
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
            # Specialist/scope as recorded with the question (answers from before
            # 2026-09-26 have none; the browser's current picker is not a proxy).
            persona=context["persona"],
            scope=_scope_text(context["scope"]),
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


async def _read_screenshot(screenshot: Optional[UploadFile]) -> Optional[tuple[bytes, str]]:
    """(bytes, 'png'|'jpg') of a valid screenshot, None if none was sent."""
    if screenshot is None:
        return None
    data = await screenshot.read(store.MAX_ATTACHMENT_BYTES + 1)
    if not data:
        return None
    if len(data) > store.MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "The screenshot is larger than 5 MB")
    kind = store.image_kind(data)
    if kind is None:
        raise HTTPException(415, "The screenshot must be a PNG or JPEG image")
    return data, kind


@router.post("/api/feedback/general")
async def save_general_feedback(
    category: Literal["stuck", "wrong_result", "inappropriate_inaccurate", "other"] = Form(...),
    comment: str = Form("", max_length=MAX_GENERAL_COMMENT),
    page: str = Form("", max_length=300),
    chat_id: str = Form("", max_length=100),
    answer_id: str = Form("", max_length=12),
    screenshot: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    """The global "Give feedback" form: category, text, optional screenshot."""
    require_enabled()
    comment = _clean(comment)
    image = await _read_screenshot(screenshot)
    if not comment and image is None:
        raise HTTPException(422, "Please describe what happened or attach a screenshot")
    attachment_path = store.save_attachment(*image) if image else ""
    try:
        saved = await _save_general(user, category=category, comment=comment, page=page,
                                    chat_id=chat_id, answer_id=answer_id, attachment_path=attachment_path)
    except BaseException:
        if attachment_path:
            store.remove_attachment(attachment_path)
        raise
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
    channel: Optional[Literal["chat", "voice", "general"]] = None,
    category: Optional[Literal["stuck", "wrong_result", "inappropriate_inaccurate", "other"]] = None,
    limit: int = Query(1000, ge=1, le=5000),
    format: Literal["json", "csv", "zip"] = "json",
    user: dict = Depends(_require_admin),
):
    """Everyone's feedback (admin only). ``from``/``to`` are UTC dates
    (inclusive); ``days`` is a shortcut for the last N days. ``cohort=__none__``
    selects users without a cohort (e.g. CGIAR staff on SSO). ``format=zip``
    returns the CSV together with the screenshots."""
    require_enabled()
    if days and not date_from:
        start = datetime.now(timezone.utc).timestamp() - (days - 1) * 86400
        date_from = datetime.fromtimestamp(start, tz=timezone.utc).date()
    result = await store.list_feedback(
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        rating=rating, cohort=cohort, channel=channel, category=category, limit=limit,
    )
    env = _environment_label()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if format == "zip":
        return Response(
            content=await store.to_zip(result["items"]),
            media_type="application/zip",
            headers={**NO_STORE, "Content-Disposition": f'attachment; filename="ia-feedback-{env}-{stamp}.zip"'},
        )
    if format == "csv":
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
                    "rating": rating, "cohort": cohort, "channel": channel, "category": category},
        **result,
    }, headers=NO_STORE)


@router.get("/api/admin/feedback/{feedback_id}/attachment")
async def admin_feedback_attachment(feedback_id: int, user: dict = Depends(_require_admin)):
    """The screenshot of one feedback submission (admin only, Bearer token)."""
    require_enabled()
    row = await store.get_feedback_row(feedback_id)
    path = store.attachment_file(row.get("attachment_path", "")) if row else None
    if path is None:
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(
        path,
        media_type="image/png" if path.suffix == ".png" else "image/jpeg",
        filename=f"feedback-{feedback_id}{path.suffix}",
        content_disposition_type="inline",
        headers={**NO_STORE, "Content-Security-Policy": "default-src 'none'; sandbox",
                 "X-Content-Type-Options": "nosniff"},
    )
