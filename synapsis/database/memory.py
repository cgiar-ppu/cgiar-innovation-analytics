"""Memory context loading for conversation injection."""

import aiosqlite

from synapsis.config import logger
from synapsis.constants import MAX_CONTEXT_MEMORIES
from synapsis.database.connection import _get_shared_db


async def load_memories_context() -> str:
    """Load top-priority memories for injection into conversation context.

    Fetches up to MAX_CONTEXT_MEMORIES active memories ordered by importance
    (descending) then recency, and formats them as a human-readable block.

    Returns:
        A newline-joined string of memory entries prefixed with category and
        importance, or an empty string if no active memories exist or a
        database error occurs.
    """
    try:
        db = await _get_shared_db()
        cursor = await db.execute(
            "SELECT category, content, importance FROM memories "
            "WHERE active = 1 ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (MAX_CONTEXT_MEMORIES,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""

        lines = ["[Persistent memories from previous sessions:]"]
        for r in rows:
            lines.append(f"- ({r['category']}, importance={r['importance']}) {r['content']}")
        return "\n".join(lines)
    except (aiosqlite.OperationalError, aiosqlite.DatabaseError) as e:
        logger.debug("Memory load error: %s", e)
        return ""
