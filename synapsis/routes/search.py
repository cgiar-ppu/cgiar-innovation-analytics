"""
Full-text conversation search endpoint.

- GET /api/search?q=keyword&limit=50 — Search across all user and assistant messages
"""

import json
from datetime import datetime

from fastapi import APIRouter

from synapsis.database import get_db

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
async def search_conversations(q: str = "", limit: int = 50):
    """Search across all conversation messages."""
    if not q.strip():
        return {"results": []}

    search_term = f"%{q.strip()}%"
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT m.session_id, m.type, m.data, m.ts,
                   COALESCE(s.title, '') as session_title
            FROM messages m
            LEFT JOIN sessions s ON m.session_id = s.session_id
            WHERE m.type IN ('user', 'text')
              AND m.data LIKE ?
            ORDER BY m.ts DESC
            LIMIT ?
        """, (search_term, limit))

        rows = await cursor.fetchall()
        results = []
        seen_sessions = set()

        for row in rows:
            data = json.loads(row["data"])
            content = data.get("content", "")
            session_id = row["session_id"]

            # Find the matching snippet
            lower_content = content.lower()
            lower_q = q.lower()
            idx = lower_content.find(lower_q)
            if idx == -1:
                continue

            # Extract snippet with context
            start = max(0, idx - 60)
            end = min(len(content), idx + len(q) + 60)
            snippet = content[start:end]
            if start > 0:
                snippet = "…" + snippet
            if end < len(content):
                snippet = snippet + "…"

            # Get session title fallback
            session_title = row["session_title"]
            if not session_title and session_id not in seen_sessions:
                c2 = await db.execute(
                    "SELECT data FROM messages WHERE session_id = ? AND type = 'user' ORDER BY ts LIMIT 1",
                    (session_id,),
                )
                preview_row = await c2.fetchone()
                if preview_row:
                    d = json.loads(preview_row["data"])
                    session_title = d.get("content", "")[:80]

            seen_sessions.add(session_id)

            results.append({
                "session_id": session_id,
                "session_title": session_title or "Untitled",
                "message_type": row["type"],
                "snippet": snippet,
                "timestamp": datetime.fromtimestamp(row["ts"]).isoformat(),
            })

        return {"results": results, "query": q}
