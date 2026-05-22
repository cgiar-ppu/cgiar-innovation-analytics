"""Task status tracking for chat sessions."""

import time
from typing import Optional

from synapsis.database.connection import _get_shared_db


async def update_session_task_status(session_id: str, status: str) -> None:
    """Update the task_status column for a chat session.

    Args:
        session_id: The application-level session identifier.
        status:     One of "idle", "running", "completed", "cancelled", "failed".
    """
    db = await _get_shared_db()
    await db.execute(
        "UPDATE sessions SET task_status = ?, updated_at = ? WHERE session_id = ?",
        (status, time.time(), session_id),
    )
    await db.commit()


async def get_session_task_status(session_id: str) -> Optional[str]:
    """Retrieve the current task_status for a chat session.

    Args:
        session_id: The application-level session identifier.

    Returns:
        The task status string, or None if the session does not exist.
    """
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT task_status FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    return row["task_status"] if row else None
