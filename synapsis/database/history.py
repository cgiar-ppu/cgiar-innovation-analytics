"""Chat history indexing and search — FTS5-backed clean conversation index.

Provides functions to:
- Build/rebuild a full-text search index of clean conversation text
- Search across all sessions by keyword
- Retrieve full conversations with tool noise filtered out

The index stores only user messages and assistant text responses, stripping
tool_use, tool_result, thinking, and system messages to minimize token count
when retrieving past conversations.
"""

import json
import time
from datetime import datetime

import aiosqlite

from synapsis.config import logger
from synapsis.database.connection import get_db, _get_shared_db


# ---------------------------------------------------------------------------
# Schema migration — adds history tables if missing
# ---------------------------------------------------------------------------

async def init_history_tables() -> None:
    """Create the history index tables if they don't exist."""
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                first_prompt TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL,
                message_count INTEGER DEFAULT 0,
                clean_text_length INTEGER DEFAULT 0,
                indexed_at REAL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS history_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                clean_text TEXT NOT NULL,
                timestamp REAL,
                FOREIGN KEY (session_id) REFERENCES history_sessions(session_id)
                    ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_chunks_session
            ON history_chunks (session_id, chunk_index)
        """)

        # FTS5 virtual table for keyword search
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='history_fts'"
        )
        if not await cursor.fetchone():
            await db.execute("""
                CREATE VIRTUAL TABLE history_fts USING fts5(
                    clean_text,
                    session_id UNINDEXED,
                    chunk_id UNINDEXED
                )
            """)

        await db.commit()


# ---------------------------------------------------------------------------
# Indexing — extract clean text from messages table
# ---------------------------------------------------------------------------

def _extract_clean_text(msg_type: str, data_str: str) -> str | None:
    """Extract human-readable text from a message, or None if it should be skipped.

    Filters:
    - user messages: returns the content text
    - text (assistant): returns the content text
    - tool_use, tool_result, thinking, result, system: returns None (skipped)
    """
    if msg_type not in ("user", "text"):
        return None

    try:
        data = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return None

    content = data.get("content", "")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


async def index_session(session_id: str) -> dict:
    """Index a single session — extract clean text and store in FTS index.

    Returns a summary dict with session_id, message_count, clean_text_length.
    """
    async with get_db() as db:
        # Get session metadata
        cursor = await db.execute(
            "SELECT title, created_at, updated_at FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        session_row = await cursor.fetchone()
        if not session_row:
            return {"session_id": session_id, "error": "Session not found"}

        # Get all messages
        cursor = await db.execute(
            "SELECT type, data, ts FROM messages WHERE session_id = ? ORDER BY ts",
            (session_id,),
        )
        rows = await cursor.fetchall()

        # Clear existing index for this session (re-index)
        await db.execute("DELETE FROM history_chunks WHERE session_id = ?", (session_id,))
        await db.execute(
            "DELETE FROM history_fts WHERE session_id = ?", (session_id,)
        )
        await db.execute("DELETE FROM history_sessions WHERE session_id = ?", (session_id,))

        # Extract clean text
        chunks = []
        first_prompt = ""
        total_length = 0

        for row in rows:
            text = _extract_clean_text(row["type"], row["data"])
            if text:
                role = "user" if row["type"] == "user" else "assistant"
                chunks.append({
                    "role": role,
                    "text": text,
                    "ts": row["ts"],
                })
                total_length += len(text)
                if role == "user" and not first_prompt:
                    first_prompt = text[:200]

        if not chunks:
            return {"session_id": session_id, "message_count": 0, "clean_text_length": 0}

        # Insert session record
        now = time.time()
        await db.execute(
            """INSERT INTO history_sessions
               (session_id, title, first_prompt, created_at, updated_at,
                message_count, clean_text_length, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                session_row["title"] or first_prompt[:80],
                first_prompt,
                session_row["created_at"],
                session_row["updated_at"],
                len(chunks),
                total_length,
                now,
            ),
        )

        # Insert chunks and FTS entries
        for i, chunk in enumerate(chunks):
            cursor = await db.execute(
                """INSERT INTO history_chunks
                   (session_id, chunk_index, role, clean_text, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, i, chunk["role"], chunk["text"], chunk["ts"]),
            )
            chunk_id = cursor.lastrowid
            await db.execute(
                "INSERT INTO history_fts (clean_text, session_id, chunk_id) VALUES (?, ?, ?)",
                (chunk["text"], session_id, chunk_id),
            )

        await db.commit()

    return {
        "session_id": session_id,
        "message_count": len(chunks),
        "clean_text_length": total_length,
    }


async def index_all_sessions(force: bool = False) -> dict:
    """Index all sessions. If force=False, only index new/updated sessions.

    Returns a summary dict with total sessions indexed and skipped.
    """
    async with get_db() as db:
        # Get all sessions
        cursor = await db.execute(
            "SELECT session_id, updated_at FROM sessions ORDER BY updated_at DESC"
        )
        all_sessions = await cursor.fetchall()

        # Get already-indexed sessions
        indexed = {}
        if not force:
            cursor = await db.execute(
                "SELECT session_id, indexed_at FROM history_sessions"
            )
            for row in await cursor.fetchall():
                indexed[row["session_id"]] = row["indexed_at"]

    results = {"indexed": 0, "skipped": 0, "errors": 0, "total": len(all_sessions)}

    for session in all_sessions:
        sid = session["session_id"]

        # Skip if already indexed and not updated since
        if not force and sid in indexed:
            if indexed[sid] >= session["updated_at"]:
                results["skipped"] += 1
                continue

        try:
            await index_session(sid)
            results["indexed"] += 1
        except Exception as e:
            logger.warning("Failed to index session %s: %s", sid, e)
            results["errors"] += 1

    return results


# ---------------------------------------------------------------------------
# Search — FTS5 keyword search across all sessions
# ---------------------------------------------------------------------------

async def search_history(
    query: str,
    limit: int = 20,
    session_filter: str = "",
) -> list[dict]:
    """Search the history index by keyword.

    Args:
        query: FTS5 search query (keywords, quoted phrases, OR/AND operators).
        limit: Maximum results to return.
        session_filter: Optional session_id to restrict search to.

    Returns:
        List of result dicts with session_id, title, role, snippet, timestamp, score.
    """
    if not query.strip():
        return []

    async with get_db() as db:
        if session_filter:
            cursor = await db.execute("""
                SELECT
                    fts.session_id,
                    fts.chunk_id,
                    snippet(history_fts, 0, '**', '**', '...', 40) AS snippet,
                    rank
                FROM history_fts fts
                WHERE history_fts MATCH ?
                  AND fts.session_id = ?
                ORDER BY rank
                LIMIT ?
            """, (query, session_filter, limit))
        else:
            cursor = await db.execute("""
                SELECT
                    fts.session_id,
                    fts.chunk_id,
                    snippet(history_fts, 0, '**', '**', '...', 40) AS snippet,
                    rank
                FROM history_fts fts
                WHERE history_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit))

        fts_rows = await cursor.fetchall()
        if not fts_rows:
            return []

        results = []
        for row in fts_rows:
            # Get chunk metadata
            cursor2 = await db.execute(
                "SELECT role, timestamp FROM history_chunks WHERE id = ?",
                (row["chunk_id"],),
            )
            chunk_row = await cursor2.fetchone()

            # Get session title
            cursor3 = await db.execute(
                "SELECT title, first_prompt, created_at FROM history_sessions WHERE session_id = ?",
                (row["session_id"],),
            )
            session_row = await cursor3.fetchone()

            title = ""
            created_at = ""
            if session_row:
                title = session_row["title"] or session_row["first_prompt"][:80]
                created_at = datetime.fromtimestamp(session_row["created_at"]).isoformat()

            results.append({
                "session_id": row["session_id"],
                "title": title,
                "role": chunk_row["role"] if chunk_row else "unknown",
                "snippet": row["snippet"],
                "timestamp": (
                    datetime.fromtimestamp(chunk_row["timestamp"]).isoformat()
                    if chunk_row else ""
                ),
                "session_created_at": created_at,
            })

    return results


# ---------------------------------------------------------------------------
# Retrieve — get clean conversation without tool noise
# ---------------------------------------------------------------------------

async def retrieve_conversation(
    session_id: str,
    include_tool_results: bool = False,
    include_thinking: bool = False,
    max_chars: int = 0,
) -> dict:
    """Retrieve a full conversation, clean (no tool noise by default).

    Args:
        session_id: The session to retrieve.
        include_tool_results: If True, include tool_use and tool_result messages.
        include_thinking: If True, include thinking blocks.
        max_chars: If > 0, truncate total output to this many characters.

    Returns:
        Dict with session metadata and list of clean messages.
    """
    async with get_db() as db:
        # Get session info
        cursor = await db.execute(
            "SELECT title, created_at, updated_at, message_count FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        session_row = await cursor.fetchone()
        if not session_row:
            return {"error": f"Session {session_id} not found"}

        # Determine which message types to include
        types = ["user", "text"]
        if include_tool_results:
            types.extend(["tool_use", "tool_result"])
        if include_thinking:
            types.append("thinking")

        placeholders = ",".join("?" for _ in types)
        cursor = await db.execute(
            f"SELECT type, data, ts FROM messages WHERE session_id = ? AND type IN ({placeholders}) ORDER BY ts",
            (session_id, *types),
        )
        rows = await cursor.fetchall()

        # Also get title from first user message if needed
        title = session_row["title"]
        if not title:
            cursor2 = await db.execute(
                "SELECT data FROM messages WHERE session_id = ? AND type = 'user' ORDER BY ts LIMIT 1",
                (session_id,),
            )
            preview_row = await cursor2.fetchone()
            if preview_row:
                d = json.loads(preview_row["data"])
                title = d.get("content", "Untitled")[:80]

    # Build clean message list
    messages = []
    total_chars = 0

    for row in rows:
        try:
            data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue

        content = data.get("content", "")
        if isinstance(content, str):
            content = content.strip()
        else:
            content = str(content)

        if not content:
            continue

        # Truncation check
        if max_chars > 0 and total_chars + len(content) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 100:
                content = content[:remaining] + "\n\n[... truncated ...]"
                messages.append({
                    "role": "user" if row["type"] == "user" else "assistant",
                    "type": row["type"],
                    "content": content,
                    "timestamp": datetime.fromtimestamp(row["ts"]).isoformat(),
                })
            break

        total_chars += len(content)

        role = "user" if row["type"] == "user" else "assistant"
        messages.append({
            "role": role,
            "type": row["type"],
            "content": content,
            "timestamp": datetime.fromtimestamp(row["ts"]).isoformat(),
        })

    return {
        "session_id": session_id,
        "title": title or "Untitled",
        "created_at": datetime.fromtimestamp(session_row["created_at"]).isoformat(),
        "updated_at": datetime.fromtimestamp(session_row["updated_at"]).isoformat(),
        "total_messages_in_db": session_row["message_count"],
        "clean_messages_returned": len(messages),
        "total_clean_chars": total_chars,
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# List sessions — for browsing history
# ---------------------------------------------------------------------------

async def list_indexed_sessions(limit: int = 50) -> list[dict]:
    """List all indexed sessions with metadata, most recent first."""
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT session_id, title, first_prompt, created_at, updated_at,
                   message_count, clean_text_length, indexed_at
            FROM history_sessions
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()

    return [
        {
            "session_id": r["session_id"],
            "title": r["title"] or r["first_prompt"][:80],
            "created_at": datetime.fromtimestamp(r["created_at"]).isoformat(),
            "updated_at": datetime.fromtimestamp(r["updated_at"]).isoformat(),
            "message_count": r["message_count"],
            "clean_text_length": r["clean_text_length"],
            "estimated_tokens": r["clean_text_length"] // 4,  # rough token estimate
        }
        for r in rows
    ]
