"""Test-round budget state and spend sums (SYN-2306, 2026-10-14).

Reads the per-question ledger (``usage_events``, see ``usage.py``) to answer:

- how much has this environment spent since the test window opened
  (``spent_between``; voice minutes converted to USD at
  ``IA_VOICE_USD_PER_MINUTE`` because voice is metered in minutes);
- how much has one chat session spent (``spent_in_session``).

It also keeps a tiny key/value table, ``budget_state``, for two facts that
must survive restarts (the chat DB is replicated by Litestream):

- ``test_start``: when ``IA_TEST_START`` is not set, the moment this
  environment first ran with the budget feature ("promotion day");
- ``alert:<window start>:<fraction>``: one row per crossed alert threshold, so
  each threshold is logged exactly once per test window, across restarts.

The policy decisions (who is blocked, which message) live in
``synapsis.runtime_policy``; this module only stores and sums.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import synapsis.config as _config
from synapsis.database.connection import get_db
from synapsis.database.usage import init_usage_table

_READY_PATHS: set[str] = set()

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS budget_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated REAL NOT NULL
    )""",
    # Window sums filter on ts; the ledger only had (user, day)/(day)/(session).
    "CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events (ts)",
)


async def init_budget_tables() -> None:
    path = str(_config.DB_PATH)
    if path in _READY_PATHS:
        return
    await init_usage_table()
    async with get_db() as db:
        for stmt in _SCHEMA:
            await db.execute(stmt)
        await db.commit()
    _READY_PATHS.add(path)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

def parse_utc(raw: str, *, end_of_day: bool = False) -> Optional[float]:
    """ISO date or date-time -> UTC epoch seconds (None when unparseable).

    A bare date means midnight UTC; with ``end_of_day`` it means the END of
    that day (so ``IA_TEST_END=2026-11-14`` keeps the 14th open).
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:  # YYYY-MM-DD
            d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if end_of_day:
                d += timedelta(days=1)
            return d.timestamp()
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        _config.logger.warning("Unparseable test window date %r - ignored", raw)
        return None


def iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


async def _get_state(db, key: str) -> Optional[str]:
    cursor = await db.execute("SELECT value FROM budget_state WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return None if row is None else str(row[0])


async def test_window(now: Optional[float] = None) -> dict:
    """``{start, end, start_source, end_source}`` as epoch seconds (UTC).

    ``start_source``: ``config`` (IA_TEST_START) or ``first_run`` (persisted the
    first time this is called on an environment without IA_TEST_START).
    """
    now = now if now is not None else time.time()
    await init_budget_tables()
    start = parse_utc(_config.TEST_START)
    start_source = "config"
    if start is None:
        start_source = "first_run"
        async with get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO budget_state (key, value, updated) VALUES ('test_start', ?, ?)",
                (repr(float(now)), now),
            )
            await db.commit()
            stored = await _get_state(db, "test_start")
        try:
            start = float(stored) if stored is not None else now
        except ValueError:
            start = now
    end = parse_utc(_config.TEST_END, end_of_day=True)
    end_source = "config"
    if end is None:
        end = start + _config.TEST_DAYS * 86400
        end_source = f"start+{_config.TEST_DAYS}d"
    return {"start": start, "end": end, "start_source": start_source, "end_source": end_source}


# ---------------------------------------------------------------------------
# Spend
# ---------------------------------------------------------------------------

async def spent_between(start: float, end: float) -> dict:
    """Model + voice spend in ``[start, end)``.

    Returns ``{model_usd, voice_minutes, voice_usd, total_usd, questions}``.
    Voice minutes come from closed provider sessions (as in the admin usage
    summary) and are converted at ``IA_VOICE_USD_PER_MINUTE``.
    """
    await init_budget_tables()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(turn_cost_usd), 0), COUNT(*) FROM usage_events WHERE ts >= ? AND ts < ?",
            (start, end),
        )
        model_usd, questions = await cursor.fetchone()
        voice_minutes = 0.0
        try:
            cursor = await db.execute(
                "SELECT COALESCE(SUM(COALESCE(provider_seconds, usage_seconds, 0)), 0) FROM voice_sessions "
                "WHERE created >= ? AND created < ? AND status = 'closed' AND sdp_hash IS NOT NULL AND sdp_hash != ''",
                (start, end),
            )
            row = await cursor.fetchone()
            voice_minutes = float(row[0] or 0.0) / 60.0
        except Exception:
            voice_minutes = 0.0  # no voice table on this deployment
    voice_usd = voice_minutes * float(_config.VOICE_USD_PER_MINUTE or 0.0)
    model_usd = float(model_usd or 0.0)
    return {
        "model_usd": model_usd,
        "voice_minutes": voice_minutes,
        "voice_usd": voice_usd,
        "total_usd": model_usd + voice_usd,
        "questions": int(questions or 0),
    }


async def spent_in_session(session_id: str) -> float:
    """Recorded model spend of one chat session (all time)."""
    await init_budget_tables()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(turn_cost_usd), 0) FROM usage_events WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
    return float(row[0] or 0.0)


# ---------------------------------------------------------------------------
# Alerts (one row per crossed threshold per window)
# ---------------------------------------------------------------------------

def _alert_key(window_start: float, fraction: float) -> str:
    return f"alert:{iso(window_start)}:{fraction:.4f}"


async def claim_alert(window_start: float, fraction: float, payload: dict) -> bool:
    """Record that ``fraction`` was crossed. True only for the first caller."""
    await init_budget_tables()
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO budget_state (key, value, updated) VALUES (?, ?, ?)",
            (_alert_key(window_start, fraction), json.dumps(payload, sort_keys=True), now),
        )
        await db.commit()
        return (cursor.rowcount or 0) > 0


async def crossed_alerts(window_start: float) -> list[dict]:
    """Alerts already recorded for this window, lowest threshold first."""
    await init_budget_tables()
    prefix = f"alert:{iso(window_start)}:"
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT key, value, updated FROM budget_state WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        )
        rows = await cursor.fetchall()
    out = []
    for key, value, updated in rows:
        try:
            payload = json.loads(value)
        except Exception:
            payload = {}
        payload.setdefault("fraction", float(key.rsplit(":", 1)[-1]))
        payload["crossed_at"] = iso(updated)
        out.append(payload)
    return sorted(out, key=lambda a: a.get("fraction", 0))
