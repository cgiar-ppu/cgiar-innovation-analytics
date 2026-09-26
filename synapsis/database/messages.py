"""Message CRUD operations for the main chat database."""

import json
import time

from synapsis.database.connection import shared_write


async def save_message(session_id: str, msg_type: str, data: dict) -> None:
    """Persist a chat message and bump the session's message count.

    Runs inside ``shared_write()``: the INSERT and UPDATE commit together, and
    a cancel landing between them rolls back instead of leaving a write
    transaction open on the shared connection (L3-10).

    Args:
        session_id: The application session UUID the message belongs to.
        msg_type:   Message type label (e.g. "user", "assistant", "tool_use").
        data:       Arbitrary message payload; serialized to JSON for storage.
    """
    now = time.time()
    payload = json.dumps(data)
    async with shared_write() as db:
        await db.execute(
            "INSERT INTO messages (session_id, ts, type, data) VALUES (?, ?, ?, ?)",
            (session_id, now, msg_type, payload),
        )
        await db.execute(
            "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
