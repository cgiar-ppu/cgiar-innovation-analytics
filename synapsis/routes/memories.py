"""
Memory CRUD REST API — for the frontend to manage memories directly.

- GET    /api/memories            — List all active memories
- POST   /api/memories            — Create a new memory
- DELETE /api/memories/{memory_id} — Soft-delete a memory

Note: The agent uses MCP tools (memory_store, memory_recall, etc.) for its own
memory operations. These REST endpoints are for the UI sidebar.
"""

import time

from fastapi import APIRouter

from synapsis.database import get_db
from synapsis.models import MemoryCreate

router = APIRouter(prefix="/api", tags=["memories"])


@router.get("/memories")
async def list_memories():
    """List all active memories sorted by importance."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM memories WHERE active = 1 ORDER BY importance DESC, updated_at DESC"
        )
        rows = await cursor.fetchall()
        return {"memories": [dict(r) for r in rows]}


@router.post("/memories")
async def create_memory(payload: MemoryCreate):
    """Create a new memory from the UI."""
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO memories (category, content, importance, source_session, created_at, updated_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (payload.category, payload.content, payload.importance, payload.source_session, now, now, payload.tags),
        )
        memory_id = cursor.lastrowid
        # Keep FTS index in sync with the main memories table
        await db.execute(
            "INSERT INTO memories_fts (rowid, content, tags) VALUES (?, ?, ?)",
            (memory_id, payload.content, payload.tags),
        )
        await db.commit()
    return {"id": memory_id, "status": "created"}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    """Soft-delete a memory (sets active=0)."""
    async with get_db() as db:
        await db.execute("UPDATE memories SET active = 0 WHERE id = ?", (memory_id,))
        await db.commit()
    return {"status": "deleted"}
