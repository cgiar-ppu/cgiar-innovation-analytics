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
from fastapi import APIRouter

from synapsis.database import get_db
from synapsis.models import SessionUpdate
from synapsis.session_manager import broadcast_to_all, broadcast_to_session

router = APIRouter(prefix="/api", tags=["sessions"])


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
async def list_sessions():
    """List all sessions with metadata, ordered by most recently updated.

    Uses a single SQL query with a subquery to fetch the first user message
    preview in one round-trip instead of N+1 queries.
    """
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT
                s.session_id,
                s.title,
                s.created_at,
                s.updated_at,
                s.model,
                s.message_count,
                s.pinned,
                s.task_status,
                (
                    SELECT m.data
                    FROM messages m
                    WHERE m.session_id = s.session_id AND m.type = 'user'
                    ORDER BY m.ts
                    LIMIT 1
                ) AS first_user_data
            FROM sessions s
            ORDER BY COALESCE(s.pinned, 0) DESC, s.updated_at DESC
        """)
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
            })
        return {"sessions": results}


@router.get("/history/{session_id}")
async def get_session_history(session_id: str):
    """Return all messages for a specific session, ordered by timestamp."""
    async with get_db() as db:
        messages = await _fetch_messages(db, session_id)
        return {"messages": messages, "session_id": session_id}


@router.get("/history")
async def get_history():
    """Return messages from the most recent session (backward compatibility)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY ts DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return {"messages": [], "session_id": None}

        sid = row["session_id"]
        messages = await _fetch_messages(db, sid)
        return {"messages": messages, "session_id": sid}


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdate):
    """Rename a session."""
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (payload.title, time.time(), session_id),
        )
        await db.commit()
    # Broadcast the rename to all connected devices
    await broadcast_to_all({"type": "sessions_changed"})
    return {"status": "updated", "session_id": session_id}


@router.post("/sessions/{session_id}/pin")
async def pin_session(session_id: str, payload: dict):
    """Toggle pin/star status on a session."""
    pinned = payload.get("pinned", True)
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET pinned = ? WHERE session_id = ?",
            (1 if pinned else 0, session_id),
        )
        await db.commit()
    return {"status": "updated", "pinned": pinned}


@router.post("/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """Generate a title from first user message. Preserves manual titles."""
    async with get_db() as db:
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
async def delete_session(session_id: str):
    """Delete a session and all its messages.

    The SDK client is disconnected FIRST to stop any active streaming task,
    then the database rows are removed. This ordering prevents a race where
    the stream handler tries to persist messages to an already-deleted session.
    """
    from synapsis.server import cleanup_session_client

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
async def clear_history():
    """Delete all messages and sessions."""
    async with get_db() as db:
        await db.execute("DELETE FROM messages")
        await db.execute("DELETE FROM sessions")
        await db.commit()
    return {"status": "cleared"}
