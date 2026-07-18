"""Session CRUD operations for the main chat database."""

import time

from synapsis.config import logger
from synapsis.database.connection import _get_shared_db


async def create_session(session_id: str, title: str = "", user_id: str | None = None) -> None:
    """Insert a new session row (no-op if it already exists).

    Args:
        session_id: Unique identifier for the session.
        title:      Optional human-readable title; defaults to empty string.
        user_id:    Owning user's stable identity claim (July-7 Step 4). When
                    None, the legacy sentinel is used so the row is never
                    silently attributed to a real user.
    """
    from synapsis.config import MODEL
    from synapsis.auth.context import get_current_user_id
    now = time.time()
    # Explicit user_id wins; otherwise fall back to the per-connection identity
    # context (set by the WebSocket handler at connect time), which itself
    # defaults to the legacy sentinel.
    owner = user_id or get_current_user_id()
    db = await _get_shared_db()
    await db.execute(
        "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at, model, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, title, now, now, MODEL, owner),
    )
    await db.commit()


async def get_session_owner(session_id: str) -> str | None:
    """Return the ``user_id`` that owns a session, or None if it doesn't exist.

    Used to enforce per-user access on history/delete/rename so a user can only
    reach their own conversations.
    """
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT user_id FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return row["user_id"] if row["user_id"] else None


async def get_session_model(session_id: str) -> str:
    """Get the model ID stored for a session.

    Args:
        session_id: The application-level session identifier.

    Returns:
        The model ID string, or an empty string if the session does not exist
        or has no model recorded (callers should treat "" as "use the server
        default").
    """
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT model FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    return row["model"] if row and row["model"] else ""


async def update_session_model(session_id: str, model: str) -> None:
    """Persist a new model ID for a session (used by mid-chat model switching).

    Args:
        session_id: The application-level session identifier.
        model:      The new model ID (already validated against SELECTABLE_MODELS).
    """
    db = await _get_shared_db()
    await db.execute(
        "UPDATE sessions SET model = ?, updated_at = ? WHERE session_id = ?",
        (model, time.time(), session_id),
    )
    await db.commit()
    logger.info("Session %s model updated to %s", session_id, model)


async def save_claude_session_id(app_session_id: str, claude_session_id: str) -> None:
    """Store the Claude SDK internal session UUID so we can resume later.

    Args:
        app_session_id:    The application-level session identifier.
        claude_session_id: The opaque session UUID returned by the Claude SDK.
    """
    db = await _get_shared_db()
    await db.execute(
        "UPDATE sessions SET claude_session_id = ? WHERE session_id = ?",
        (claude_session_id, app_session_id),
    )
    await db.commit()
    logger.info("Mapped app session %s -> Claude session %s", app_session_id, claude_session_id)


async def get_claude_session_id(app_session_id: str) -> str:
    """Retrieve the Claude SDK session UUID for an app session.

    Args:
        app_session_id: The application-level session identifier to look up.

    Returns:
        The Claude SDK session UUID string, or an empty string if the session
        does not exist or has no associated Claude session ID.
    """
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT claude_session_id FROM sessions WHERE session_id = ?",
        (app_session_id,),
    )
    row = await cursor.fetchone()
    return row["claude_session_id"] if row and row["claude_session_id"] else ""


async def save_initial_context(session_id: str, context: str) -> None:
    """Store initial context on a session for injection into the first message.

    Used by the workflow continuation feature so the Claude SDK receives the
    workflow output as part of the first user query.

    Args:
        session_id: The application-level session identifier.
        context:    The context text to prepend to the first user message.
    """
    db = await _get_shared_db()
    await db.execute(
        "UPDATE sessions SET initial_context = ? WHERE session_id = ?",
        (context, session_id),
    )
    await db.commit()


async def consume_initial_context(session_id: str) -> str:
    """Retrieve and clear the initial context for a session.

    Returns the stored initial_context string and atomically clears it so it
    is only injected once (on the first user message).

    Args:
        session_id: The application-level session identifier.

    Returns:
        The context string, or an empty string if none was stored.
    """
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT initial_context FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    context = ""
    if row and row["initial_context"]:
        context = row["initial_context"]
        await db.execute(
            "UPDATE sessions SET initial_context = '' WHERE session_id = ?",
            (session_id,),
        )
        await db.commit()
    return context
