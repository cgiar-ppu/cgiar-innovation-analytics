"""Per-question usage ledger (cost, turns, model, role) for the chat database.

Why a separate table
--------------------
The ``result`` rows in ``messages`` carry the SDK's ``total_cost_usd``, which
is a *running total for the Claude conversation* (it grows turn after turn and
is restored when a chat is resumed), not the cost of that question. Summing
them over-counts. From 2026-09-26 every finished question writes one
``usage_events`` row with the per-question delta, the caller's user id and
role at that moment, and the model. The daily cap and the admin usage summary
read this table; days before the table existed are *estimated* from the
``messages`` result rows by differencing the running totals per chat.

All writes use short-lived connections (``get_db``) so a cancelled streaming
task can never leave a transaction open on the shared connection.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import synapsis.config as _config
from synapsis.config import logger
from synapsis.database.connection import get_db

_READY_PATHS: set[str] = set()

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS usage_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        day TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        session_id TEXT,
        model TEXT,
        source TEXT NOT NULL DEFAULT 'chat',
        turn_cost_usd REAL NOT NULL DEFAULT 0,
        cumulative_cost_usd REAL,
        num_turns INTEGER,
        duration_ms INTEGER,
        is_error INTEGER NOT NULL DEFAULT 0,
        subtype TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_usage_user_day ON usage_events (user_id, day)",
    "CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_events (day)",
    "CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_events (session_id, ts)",
)


def utc_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def utc_day_start(ts: Optional[float] = None) -> float:
    now = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


async def init_usage_table() -> None:
    """Create the ledger table if needed (idempotent, cached per DB path)."""
    path = str(_config.DB_PATH)
    if path in _READY_PATHS:
        return
    async with get_db() as db:
        for stmt in _SCHEMA:
            await db.execute(stmt)
        await db.commit()
    _READY_PATHS.add(path)


def turn_cost_from_totals(cumulative: Optional[float], baseline: Optional[float]) -> float:
    """Per-question cost from the SDK running total.

    ``baseline`` is the running total seen after the previous question on the
    same Claude conversation. A total that went *down* means the counter was
    reset (fresh CLI conversation), so the whole total is this question's.
    """
    c = float(cumulative or 0.0)
    b = float(baseline or 0.0)
    if c < 0:
        return 0.0
    return c - b if c >= b else c


async def record_turn_usage(
    *,
    user_id: str,
    role: str,
    session_id: Optional[str],
    model: Optional[str],
    turn_cost_usd: float,
    cumulative_cost_usd: Optional[float] = None,
    num_turns: Optional[int] = None,
    duration_ms: Optional[int] = None,
    is_error: bool = False,
    subtype: Optional[str] = None,
    source: str = "chat",
    ts: Optional[float] = None,
) -> None:
    """Append one question to the ledger. Never raises (logged instead)."""
    now = ts if ts is not None else time.time()
    try:
        await init_usage_table()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO usage_events (ts, day, user_id, role, session_id, model, source, "
                "turn_cost_usd, cumulative_cost_usd, num_turns, duration_ms, is_error, subtype) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now, utc_day(now), user_id or "", role or "user", session_id, model or "",
                    source, max(0.0, float(turn_cost_usd or 0.0)), cumulative_cost_usd,
                    num_turns, duration_ms, 1 if is_error else 0, subtype,
                ),
            )
            await db.commit()
    except Exception:
        logger.warning("Could not record usage for session %s", session_id, exc_info=True)


async def spent_today_usd(user_id: str, now: Optional[float] = None) -> float:
    """Sum of this user's recorded per-question cost for the current UTC day."""
    await init_usage_table()
    day = utc_day(now if now is not None else time.time())
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(turn_cost_usd), 0) FROM usage_events WHERE user_id = ? AND day = ?",
            (user_id, day),
        )
        row = await cursor.fetchone()
    return float(row[0] or 0.0)


async def last_cumulative_cost(session_id: str) -> Optional[float]:
    """Latest SDK running total recorded for a chat (baseline after resume)."""
    try:
        await init_usage_table()
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT cumulative_cost_usd FROM usage_events WHERE session_id = ? "
                "AND cumulative_cost_usd IS NOT NULL ORDER BY ts DESC, id DESC LIMIT 1",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is not None and row[0] is not None:
                return float(row[0])
            # Chats that predate the ledger: last result row in messages.
            cursor = await db.execute(
                "SELECT data FROM messages WHERE session_id = ? AND type = 'result' "
                "ORDER BY ts DESC, id DESC LIMIT 1",
                (session_id,),
            )
            row = await cursor.fetchone()
    except Exception:
        logger.debug("last_cumulative_cost failed for %s", session_id, exc_info=True)
        return None
    if row is None:
        return None
    import json
    try:
        value = json.loads(row[0]).get("estimated_cost")
    except Exception:
        return None
    return float(value) if isinstance(value, (int, float)) else None


# ---------------------------------------------------------------------------
# Aggregation for GET /api/admin/usage
# ---------------------------------------------------------------------------

def _empty_day(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "turns": 0,
        "sessions": 0,
        "users": 0,
        "cost_usd": 0.0,
        "errors": 0,
        "by_role": {},
        "by_model": {},
        "by_cohort": {},
        "voice": {"sessions": 0, "minutes": 0.0},
        "source": "none",
    }


async def _role_lookup(db) -> dict[str, str]:
    """user_id -> role for identities we can resolve (never returned to clients)."""
    roles: dict[str, str] = {}
    for sql in (
        "SELECT user_id, role FROM sso_identities",
        "SELECT email, role FROM users",
    ):
        try:
            cursor = await db.execute(sql)
            for uid, role in await cursor.fetchall():
                roles[str(uid)] = str(role or "researcher")
        except Exception:
            continue
    return roles


def _legacy_role(user_id: str, roles: dict[str, str]) -> str:
    if user_id in roles:
        return roles[user_id]
    if user_id.startswith("invited:"):
        return "researcher"
    if user_id == _config.LEGACY_USER_ID:
        return "legacy"
    return "unknown"


async def usage_summary(days: int, now: Optional[float] = None) -> dict[str, Any]:
    """Per-day turns/sessions/users/cost by role and model (+ voice).

    ``source`` per day: ``recorded`` (ledger), ``estimated`` (differenced from
    chat history, before the ledger existed), ``mixed`` or ``none``.
    """
    import json

    now = now if now is not None else time.time()
    days = max(1, min(int(days), 366))
    start = utc_day_start(now) - (days - 1) * 86400
    await init_usage_table()

    by_day: dict[str, dict[str, Any]] = {}
    sessions_by_day: dict[str, set] = {}
    users_by_day: dict[str, set] = {}
    role_users: dict[tuple[str, str], set] = {}
    sources: dict[str, set] = {}
    # Test-round cohort of invited users (Lane H); labels only, no identities.
    cohort_of: dict[str, str] = {}
    cohort_users: dict[tuple[str, str], set] = {}

    def add(day, user_id, role, session_id, model, cost, is_error, source):
        d = by_day.setdefault(day, _empty_day(day))
        d["turns"] += 1
        d["cost_usd"] += cost
        d["errors"] += 1 if is_error else 0
        sessions_by_day.setdefault(day, set()).add(session_id)
        users_by_day.setdefault(day, set()).add(user_id)
        r = d["by_role"].setdefault(role, {"turns": 0, "cost_usd": 0.0, "users": 0})
        r["turns"] += 1
        r["cost_usd"] += cost
        role_users.setdefault((day, role), set()).add(user_id)
        m = d["by_model"].setdefault(model or "default", {"turns": 0, "cost_usd": 0.0})
        m["turns"] += 1
        m["cost_usd"] += cost
        cohort = cohort_of.get(user_id)
        if cohort:
            c = d["by_cohort"].setdefault(cohort, {"turns": 0, "cost_usd": 0.0, "users": 0})
            c["turns"] += 1
            c["cost_usd"] += cost
            cohort_users.setdefault((day, cohort), set()).add(user_id)
        sources.setdefault(day, set()).add(source)

    async with get_db() as db:
        try:
            cursor = await db.execute("SELECT user_id, cohort FROM invited_accounts WHERE cohort != ''")
            cohort_of.update({str(u): str(c) for u, c in await cursor.fetchall()})
        except Exception:
            pass  # no invited accounts table / pre-cohort schema
        cursor = await db.execute("SELECT MIN(ts) FROM usage_events")
        row = await cursor.fetchone()
        cutover = float(row[0]) if row and row[0] is not None else float("inf")

        cursor = await db.execute(
            "SELECT ts, user_id, role, session_id, model, turn_cost_usd, is_error "
            "FROM usage_events WHERE ts >= ? ORDER BY ts",
            (start,),
        )
        for ts, uid, role, sid, model, cost, err in await cursor.fetchall():
            add(utc_day(ts), uid, role, sid, model, float(cost or 0.0), bool(err), "recorded")

        # Estimated history before the ledger existed.
        if start < cutover:
            roles = await _role_lookup(db)
            cursor = await db.execute(
                "SELECT m.session_id, m.ts, m.data, s.user_id, s.model FROM messages m "
                "LEFT JOIN sessions s ON s.session_id = m.session_id "
                "WHERE m.type = 'result' AND m.ts < ? ORDER BY m.session_id, m.ts, m.id",
                (cutover,),
            )
            prev: dict[str, float] = {}
            for sid, ts, data, uid, model in await cursor.fetchall():
                try:
                    payload = json.loads(data)
                except Exception:
                    continue
                total = payload.get("estimated_cost")
                if not isinstance(total, (int, float)):
                    continue
                cost = turn_cost_from_totals(total, prev.get(sid))
                prev[sid] = float(total)
                if ts < start:
                    continue
                uid = uid or _config.LEGACY_USER_ID
                add(utc_day(ts), uid, _legacy_role(uid, roles), sid, model,
                    cost, bool(payload.get("is_error")), "estimated")

        voice: dict[str, dict[str, float]] = {}
        try:
            cursor = await db.execute(
                "SELECT created, COALESCE(provider_seconds, usage_seconds, 0), status, sdp_hash "
                "FROM voice_sessions WHERE created >= ?",
                (start,),
            )
            for created, seconds, status, sdp_hash in await cursor.fetchall():
                if not sdp_hash:
                    continue
                v = voice.setdefault(utc_day(created), {"sessions": 0, "minutes": 0.0})
                v["sessions"] += 1
                if status == "closed":
                    v["minutes"] += float(seconds or 0.0) / 60.0
        except Exception:
            voice = {}

    daily = []
    for i in range(days):
        day = utc_day(start + i * 86400 + 1)
        d = by_day.get(day, _empty_day(day))
        d["sessions"] = len(sessions_by_day.get(day, ()))
        d["users"] = len(users_by_day.get(day, ()))
        for role, r in d["by_role"].items():
            r["users"] = len(role_users.get((day, role), ()))
            r["cost_usd"] = round(r["cost_usd"], 4)
        for m in d["by_model"].values():
            m["cost_usd"] = round(m["cost_usd"], 4)
        for cohort, c in d["by_cohort"].items():
            c["users"] = len(cohort_users.get((day, cohort), ()))
            c["cost_usd"] = round(c["cost_usd"], 4)
        d["cost_usd"] = round(d["cost_usd"], 4)
        src = sources.get(day, set())
        d["source"] = "mixed" if len(src) > 1 else (next(iter(src)) if src else "none")
        if day in voice:
            d["voice"] = {"sessions": int(voice[day]["sessions"]),
                          "minutes": round(voice[day]["minutes"], 1)}
        daily.append(d)

    all_users = set().union(*users_by_day.values()) if users_by_day else set()
    all_sessions = set().union(*sessions_by_day.values()) if sessions_by_day else set()
    totals = {
        "turns": sum(d["turns"] for d in daily),
        "sessions": len(all_sessions),
        "users": len(all_users),
        "cost_usd": round(sum(d["cost_usd"] for d in daily), 4),
        "errors": sum(d["errors"] for d in daily),
        "voice_sessions": sum(d["voice"]["sessions"] for d in daily),
        "voice_minutes": round(sum(d["voice"]["minutes"] for d in daily), 1),
    }
    return {
        "from": utc_day(start),
        "to": utc_day(now),
        "days": days,
        "totals": totals,
        "daily": daily,
        "ledger_since": None if cutover == float("inf") else datetime.fromtimestamp(
            cutover, tz=timezone.utc).isoformat(timespec="seconds"),
    }
