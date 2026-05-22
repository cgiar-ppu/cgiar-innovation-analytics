"""Message CRUD operations for the main chat database."""

import json
import time

from synapsis.database.connection import _get_shared_db


async def save_message(session_id: str, msg_type: str, data: dict) -> None:
    """Persist a chat message and bump the session's message count.

    Args:
        session_id: The application session UUID the message belongs to.
        msg_type:   Message type label (e.g. "user", "assistant", "tool_use").
        data:       Arbitrary message payload; serialized to JSON for storage.
    """
    now = time.time()
    db = await _get_shared_db()
    await db.execute(
        "INSERT INTO messages (session_id, ts, type, data) VALUES (?, ?, ?, ?)",
        (session_id, now, msg_type, json.dumps(data)),
    )
    await db.execute(
        "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    await db.commit()
