"""
Memory MCP tools — persistent memory store backed by SQLite + FTS5.

Provides four tools the agent can call:
- memory_store:  Save a new memory (or update an existing duplicate)
- memory_recall: Search memories by keyword/category via full-text search
- memory_list:   List all active memories sorted by importance
- memory_forget: Soft-delete a memory by ID (sets active=0)
"""

import time
from datetime import datetime
from typing import Any

from claude_agent_sdk import tool
from synapsis.database import get_db
from synapsis.utils.responses import error_response, success_response


# ---------------------------------------------------------------------------
# memory_store
# ---------------------------------------------------------------------------

@tool("memory_store", "Store a persistent memory for future sessions", {
    "category": str,
    "content": str,
    "importance": int,
    "tags": str,
})
async def memory_store(args: dict[str, Any]) -> dict[str, Any]:
    """Save a memory to the persistent database.

    If an exact duplicate (same category + content) exists, update its
    importance and tags instead of inserting a new row.
    """
    category = args.get("category", "fact")
    content = args.get("content", "")
    importance = args.get("importance", 5)
    tags = args.get("tags", "")

    if not content:
        return error_response("Error: content is required")

    now = time.time()
    async with get_db() as db:
        # Check for duplicate memory (same category + content, still active)
        cursor = await db.execute(
            "SELECT id, content FROM memories WHERE active = 1 AND category = ? AND content = ?",
            (category, content),
        )
        existing = await cursor.fetchone()

        if existing:
            # Update in place rather than creating a duplicate row
            await db.execute(
                "UPDATE memories SET importance = ?, tags = ?, updated_at = ? WHERE id = ?",
                (importance, tags, now, existing[0]),
            )
            await db.commit()
            return success_response(f"Updated existing memory (id={existing[0]}).")

        # Insert new memory + update FTS index
        cursor = await db.execute(
            """INSERT INTO memories (category, content, importance, source_session, created_at, updated_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (category, content, importance, "", now, now, tags),
        )
        memory_id = cursor.lastrowid
        await db.execute(
            "INSERT INTO memories_fts (rowid, content, tags) VALUES (?, ?, ?)",
            (memory_id, content, tags),
        )
        await db.commit()

    return success_response(f"Memory stored (id={memory_id}, category={category}).")


# ---------------------------------------------------------------------------
# memory_recall
# ---------------------------------------------------------------------------

@tool("memory_recall", "Search persistent memories by keyword or category", {
    "query": str,
    "category": str,
    "limit": int,
})
async def memory_recall(args: dict[str, Any]) -> dict[str, Any]:
    """Search memories using FTS5 full-text search.

    Can filter by category and/or free-text query. Updates access_count
    on each returned memory.
    """
    search_query = args.get("query", "")
    category = args.get("category", "")
    limit = args.get("limit", 10)

    async with get_db() as db:
        if search_query:
            # FTS5 match joined back to the main table for metadata
            sql = """
                SELECT m.id, m.category, m.content, m.importance, m.tags,
                       m.created_at, m.updated_at, m.access_count
                FROM memories m
                JOIN memories_fts fts ON m.id = fts.rowid
                WHERE memories_fts MATCH ? AND m.active = 1
            """
            params: list = [search_query]
            if category:
                sql += " AND m.category = ?"
                params.append(category)
            sql += " ORDER BY m.importance DESC, m.updated_at DESC LIMIT ?"
            params.append(limit)

        elif category:
            # Category-only filter (no FTS needed)
            sql = """
                SELECT id, category, content, importance, tags,
                       created_at, updated_at, access_count
                FROM memories WHERE active = 1 AND category = ?
                ORDER BY importance DESC, updated_at DESC LIMIT ?
            """
            params = [category, limit]

        else:
            # No filters: return most important/recent memories
            sql = """
                SELECT id, category, content, importance, tags,
                       created_at, updated_at, access_count
                FROM memories WHERE active = 1
                ORDER BY importance DESC, updated_at DESC LIMIT ?
            """
            params = [limit]

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()

        # Bump access counts so frequently-recalled memories are surfaced
        for row in rows:
            await db.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                (row["id"],),
            )
        await db.commit()

        if not rows:
            return success_response("No memories found.")

        memories = []
        for r in rows:
            memories.append(
                f"[{r['id']}] ({r['category']}) importance={r['importance']} "
                f"tags={r['tags']}\n  {r['content']}"
            )
        return success_response("Memories found:\n" + "\n".join(memories))


# ---------------------------------------------------------------------------
# memory_list
# ---------------------------------------------------------------------------

@tool("memory_list", "List all persistent memories, optionally filtered by category", {
    "category": str,
    "limit": int,
})
async def memory_list(args: dict[str, Any]) -> dict[str, Any]:
    """List memories sorted by importance (descending)."""
    category = args.get("category", "")
    limit = args.get("limit", 20)

    async with get_db() as db:
        if category:
            cursor = await db.execute(
                "SELECT * FROM memories WHERE active = 1 AND category = ? "
                "ORDER BY importance DESC, updated_at DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM memories WHERE active = 1 "
                "ORDER BY importance DESC, updated_at DESC LIMIT ?",
                (limit,),
            )

        rows = await cursor.fetchall()
        if not rows:
            return success_response("No memories stored yet.")

        lines = []
        for r in rows:
            dt = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"[{r['id']}] ({r['category']}) importance={r['importance']} "
                f"accessed={r['access_count']}x created={dt}\n  {r['content']}"
            )
        return success_response("All memories:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# memory_forget
# ---------------------------------------------------------------------------

@tool("memory_forget", "Remove a memory by its ID (soft delete)", {
    "memory_id": int,
})
async def memory_forget(args: dict[str, Any]) -> dict[str, Any]:
    """Soft-delete a memory (sets active=0, does not physically remove the row)."""
    memory_id = args.get("memory_id", 0)

    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE memories SET active = 0 WHERE id = ? AND active = 1", (memory_id,)
        )
        if cursor.rowcount == 0:
            await db.commit()
            return error_response(f"Memory {memory_id} not found or already deleted.")
        await db.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        await db.commit()

    return success_response(f"Memory {memory_id} forgotten.")
