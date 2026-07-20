"""
Session management and chat history endpoints.

- GET    /api/sessions              — List all sessions
- GET    /api/history/{session_id}  — Get messages for a session
- GET    /api/history               — Get messages from the most recent session
- PATCH  /api/sessions/{session_id} — Rename a session
- DELETE /api/sessions/{session_id} — Delete a session and its messages
- DELETE /api/history               — Clear all history
"""

import json
import time
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from synapsis.database import get_db
from synapsis.models import SessionUpdate
from synapsis.session_manager import broadcast_to_all, broadcast_to_session
from synapsis.auth.middleware import get_current_user, resolve_user_id, resolve_role
from synapsis.auth.scoping import allowed_user_ids, is_visible_to
from synapsis.config import LEGACY_USER_ID

router = APIRouter(prefix="/api", tags=["sessions"])


async def _require_session_owner(db, session_id: str, user: dict) -> None:
    """Raise 404 unless *session_id* is visible to the identity in *user*.

    Uses 404 (not 403) so the endpoint does not leak the existence of another
    user's session — a user simply cannot see conversations that are not
    theirs. Admins additionally see sentinel-owned ("legacy" / pre-auth)
    sessions -- see synapsis.auth.scoping.is_visible_to and
    docs/SECURITY-SCOPING-NOTE.md.
    """
    cursor = await db.execute(
        "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    if row is None or not is_visible_to(row["user_id"], resolve_user_id(user), resolve_role(user)):
        raise HTTPException(status_code=404, detail="Session not found")


async def _fetch_messages(db: aiosqlite.Connection, session_id: str) -> list[dict]:
    """Fetch all messages for a session ordered by timestamp.

    Extracted helper to avoid duplicating the query in get_session_history
    and get_history.
    """
    cursor = await db.execute(
        "SELECT type, data FROM messages WHERE session_id = ? ORDER BY ts",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [{"type": r["type"], **json.loads(r["data"])} for r in rows]


@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """List the current user's sessions, ordered by most recently updated.

    Scoped to the authenticated identity (July-7 Step 4): each user only ever
    sees their own conversations. Admins ALSO see sentinel-owned ("legacy" /
    pre-auth) sessions -- see synapsis.auth.scoping.allowed_user_ids and
    docs/SECURITY-SCOPING-NOTE.md. Uses a single SQL query with a subquery to
    fetch the first user message preview in one round-trip.
    """
    user_id = resolve_user_id(user)
    role = resolve_role(user)
    ids = allowed_user_ids(user_id, role)
    placeholders = ",".join("?" for _ in ids)
    async with get_db() as db:
        cursor = await db.execute(f"""
            SELECT
                s.session_id,
                s.title,
                s.created_at,
                s.updated_at,
                s.model,
                s.message_count,
                s.pinned,
                s.task_status,
                s.user_id,
                (
                    SELECT m.data
                    FROM messages m
                    WHERE m.session_id = s.session_id AND m.type = 'user'
                    ORDER BY m.ts
                    LIMIT 1
                ) AS first_user_data
            FROM sessions s
            WHERE s.user_id IN ({placeholders})
            ORDER BY COALESCE(s.pinned, 0) DESC, s.updated_at DESC
        """, tuple(ids))
        results = []
        for row in await cursor.fetchall():
            title = row["title"]
            if not title and row["first_user_data"]:
                d = json.loads(row["first_user_data"])
                title = d.get("content", "")[:80]

            results.append({
                "session_id": row["session_id"],
                "title": title,
                "created_at": datetime.fromtimestamp(row["created_at"]).isoformat(),
                "updated_at": datetime.fromtimestamp(row["updated_at"]).isoformat(),
                "model": row["model"],
                "message_count": row["message_count"],
                "pinned": bool(row["pinned"]),
                "task_status": row["task_status"],
                # Cheap, purely-informational marker: only ever true for an
                # admin viewing a sentinel-owned pre-auth session (never for
                # the sentinel's own live sessions, since only admins ever
                # see rows whose owner != their own user_id here).
                "is_legacy": row["user_id"] == LEGACY_USER_ID and user_id != LEGACY_USER_ID,
            })
        return {"sessions": results}


@router.get("/history/{session_id}")
async def get_session_history(session_id: str, user: dict = Depends(get_current_user)):
    """Return all messages for a specific session, ordered by timestamp.

    Scoped: 404 unless the session belongs to the authenticated user.
    """
    user_id = resolve_user_id(user)
    async with get_db() as db:
        await _require_session_owner(db, session_id, user)
        messages = await _fetch_messages(db, session_id)
        return {"messages": messages, "session_id": session_id}


@router.get("/history")
async def get_history(user: dict = Depends(get_current_user)):
    """Return messages from the current user's most recent session."""
    user_id = resolve_user_id(user)
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT session_id FROM sessions WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"messages": [], "session_id": None}

        sid = row["session_id"]
        messages = await _fetch_messages(db, sid)
        return {"messages": messages, "session_id": sid}


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdate, user: dict = Depends(get_current_user)):
    """Rename a session (owner-only)."""
    user_id = resolve_user_id(user)
    async with get_db() as db:
        await _require_session_owner(db, session_id, user)
        await db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (payload.title, time.time(), session_id),
        )
        await db.commit()
    # Broadcast the rename to all connected devices
    await broadcast_to_all({"type": "sessions_changed"})
    return {"status": "updated", "session_id": session_id}


@router.post("/sessions/{session_id}/pin")
async def pin_session(session_id: str, payload: dict, user: dict = Depends(get_current_user)):
    """Toggle pin/star status on a session (owner-only)."""
    user_id = resolve_user_id(user)
    pinned = payload.get("pinned", True)
    async with get_db() as db:
        await _require_session_owner(db, session_id, user)
        await db.execute(
            "UPDATE sessions SET pinned = ? WHERE session_id = ?",
            (1 if pinned else 0, session_id),
        )
        await db.commit()
    return {"status": "updated", "pinned": pinned}


@router.post("/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str, user: dict = Depends(get_current_user)):
    """Generate a title from first user message. Preserves manual titles. Owner-only."""
    user_id = resolve_user_id(user)
    async with get_db() as db:
        await _require_session_owner(db, session_id, user)
        # Check if title already set
        cursor = await db.execute("SELECT title FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()
        if row and row["title"]:
            return {"title": row["title"], "session_id": session_id}

        # Get first user message
        cursor = await db.execute(
            "SELECT data FROM messages WHERE session_id = ? AND type = 'user' ORDER BY ts LIMIT 1",
            (session_id,),
        )
        msg_row = await cursor.fetchone()
        if not msg_row:
            return {"title": "New Chat", "session_id": session_id}

        content = json.loads(msg_row["data"]).get("content", "").strip()
        title = content

        # Strip common prefixes
        for prefix in ["I want to ", "I need to ", "Can you ", "Please ",
                        "Help me ", "I'd like to ", "I would like to ", "Could you "]:
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):]
                break

        # Take first sentence
        for sep in [". ", "? ", "! ", "\n"]:
            idx = title.find(sep)
            if idx != -1 and idx < 80:
                title = title[:idx + 1]
                break

        # Truncate and capitalize
        if len(title) > 70:
            title = title[:67] + "..."
        if title:
            title = title[0].upper() + title[1:]

        await db.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                          (title, time.time(), session_id))
        await db.commit()
    return {"title": title, "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """Delete a session and all its messages (owner-only).

    The SDK client is disconnected FIRST to stop any active streaming task,
    then the database rows are removed. This ordering prevents a race where
    the stream handler tries to persist messages to an already-deleted session.
    """
    from synapsis.server import cleanup_session_client

    user_id = resolve_user_id(user)
    async with get_db() as db:
        await _require_session_owner(db, session_id, user)

    # Disconnect the SDK client first — stops active streams and removes
    # the client from the in-memory sessions dict.
    await cleanup_session_client(session_id)

    async with get_db() as db:
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await db.commit()

    await broadcast_to_all({"type": "session_update", "action": "deleted", "session_id": session_id})
    return {"status": "deleted"}


@router.delete("/history")
async def clear_history(user: dict = Depends(get_current_user)):
    """Delete the current user's messages and sessions (scoped, not global)."""
    user_id = resolve_user_id(user)
    async with get_db() as db:
        # Only delete messages belonging to this user's sessions.
        await db.execute(
            "DELETE FROM messages WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE user_id = ?)",
            (user_id,),
        )
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
    return {"status": "cleared"}
