"""
Dashboard statistics API — aggregate metrics from the database.

- GET /api/dashboard/stats    — Returns counts of sessions, messages, memories, etc.
- GET /api/dashboard/activity — Returns per-day message counts for the last N days.
"""

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from synapsis.agents import SUBAGENTS
from synapsis.database import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats")
async def dashboard_stats():
    """Return dashboard statistics from the database."""
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM sessions")
        session_count = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        message_count = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM memories WHERE active = 1")
        memory_count = (await cursor.fetchone())[0]

        week_ago = time.time() - 7 * 86400
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE ts > ?", (week_ago,)
        )
        recent_messages = (await cursor.fetchone())[0]

    # Import at call time to avoid circular imports
    from synapsis.websocket import get_activity_stats
    activity = get_activity_stats()

    return {
        "stats": [
            {"label": "Active Sessions", "value": activity.get("active_sessions", 0), "trend": 0, "trendUp": True},
            {"label": "Total Agents", "value": len(SUBAGENTS), "trend": 0, "trendUp": True},
            {"label": "Messages", "value": message_count, "trend": 0, "trendUp": True},
            {"label": "Memories Stored", "value": memory_count, "trend": 0, "trendUp": True},
            {"label": "Sessions Total", "value": session_count, "trend": 0, "trendUp": True},
            {"label": "Recent Activity (7d)", "value": recent_messages, "trend": 0, "trendUp": True},
        ],
        "agent_count": len(SUBAGENTS),
        "active_connections": activity.get("active_connections", 0),
    }


@router.get("/dashboard/activity")
async def dashboard_activity(days: int = Query(default=7, ge=1, le=90)):
    """Return per-day message counts for the last N days (default 7).

    Query params:
        days: Number of days to look back (1–90, default 7).

    Returns a JSON object with an ``activity`` array, each element being::

        {"date": "Mon", "messages": 5}

    Days with no messages are included with a count of 0 so the frontend
    always receives a complete, gapless series.
    """
    # Build a lookup of date-string -> count from the database
    cutoff_ts = time.time() - days * 86400
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT date(ts, 'unixepoch', 'localtime') AS day, COUNT(*) AS cnt
            FROM   messages
            WHERE  ts > ?
            GROUP  BY day
            ORDER  BY day ASC
            """,
            (cutoff_ts,),
        )
        rows = await cursor.fetchall()

    counts: dict[str, int] = {row["day"]: row["cnt"] for row in rows}

    # Generate a complete date series so missing days appear as 0
    today = datetime.now(tz=timezone.utc).date()
    activity = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_str = day.strftime("%Y-%m-%d")      # key used in the DB query
        label = day.strftime("%a")              # "Mon", "Tue", … for the frontend
        activity.append({"date": label, "messages": counts.get(day_str, 0)})

    return {"activity": activity}
