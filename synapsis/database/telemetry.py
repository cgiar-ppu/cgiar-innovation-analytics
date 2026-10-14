"""First-party, cookieless usage events (SYN-2305, 2026-10-14).

What and why
------------
The SPA posts small batches of interaction events to ``POST /api/telemetry``
(same origin; ``navigator.sendBeacon`` / ``fetch(keepalive)``): page views,
clicks on elements tagged ``data-track`` / ``data-testid``, and a 30-second
heartbeat while the tab is visible and in use, from which session length is
derived. No cookies, no browser storage, no third-party script and no CSP
change: events never leave this deployment.

Schema modelled on Umami
------------------------
The table follows the shape of Umami's open-source ``website_event`` model
(https://umami.is, MIT licence) so the data can be moved into a self-hosted
Umami later if dashboards are wanted:

==================  ===========================================================
``ui_events``        Umami ``website_event`` equivalent
==================  ===========================================================
``event_id``         ``event_id`` (client UUID; duplicates are ignored)
``visit_id``         ``visit_id`` (one page load of the app; in memory only)
``ts`` / ``day``     ``created_at``
``url_path``         ``url_path`` (route only; query strings are dropped)
``event_type``       ``event_type`` (1 pageview / 2 custom event); here the
                     names ``page_view`` / ``click`` / ``heartbeat`` /
                     ``visit_end``
``event_name``       ``event_name`` (the element's ``data-track`` label)
``value``            ``event_data`` numeric value (engaged seconds)
==================  ===========================================================

Unlike Umami (anonymous visitors) the app knows the signed-in account, so each
row also carries ``user_id``, ``role``, ``cohort`` (invited test cohort),
``chat_session_id`` (links to ``usage_events.session_id``) and ``env``. No
free text, element text, coordinates, user agent or IP address is stored.

Admin read-outs (``engagement_summary`` / ``engagement_csv_rows``) pseudonymise
the account as ``user_key`` (keyed hash), matching the "no identities" rule of
the admin usage endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import synapsis.config as _config
from synapsis.config import logger
from synapsis.database.connection import get_db
from synapsis.database.usage import init_usage_table, utc_day, utc_day_start

_READY_PATHS: set[str] = set()

EVENT_TYPES = ("page_view", "click", "heartbeat", "visit_end")
MAX_BATCH = 50
MAX_HEARTBEAT_SECONDS = 120.0  # one beat never claims more engaged time
_CLIENT_CLOCK_SKEW = 6 * 3600  # accept client timestamps within +-6 h

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ui_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE,
        ts REAL NOT NULL,
        day TEXT NOT NULL,
        env TEXT NOT NULL DEFAULT '',
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '',
        cohort TEXT NOT NULL DEFAULT '',
        visit_id TEXT NOT NULL,
        chat_session_id TEXT,
        event_type TEXT NOT NULL,
        url_path TEXT NOT NULL DEFAULT '',
        event_name TEXT NOT NULL DEFAULT '',
        value REAL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ui_events_day ON ui_events (day)",
    "CREATE INDEX IF NOT EXISTS idx_ui_events_user_day ON ui_events (user_id, day)",
    "CREATE INDEX IF NOT EXISTS idx_ui_events_visit ON ui_events (visit_id, ts)",
)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_NAME_RE = re.compile(r"[^A-Za-z0-9_.:/ -]")
_PATH_RE = re.compile(r"[^A-Za-z0-9_./-]")


async def init_telemetry_table() -> None:
    path = str(_config.DB_PATH)
    if path in _READY_PATHS:
        return
    async with get_db() as db:
        for stmt in _SCHEMA:
            await db.execute(stmt)
        await db.commit()
    _READY_PATHS.add(path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _clean_id(value: Any) -> Optional[str]:
    s = str(value or "").strip()
    return s if _ID_RE.match(s) else None


def _clean_path(value: Any) -> str:
    s = str(value or "").split("?", 1)[0].split("#", 1)[0].strip()
    if not s.startswith("/"):
        return ""
    return _PATH_RE.sub("", s)[:200]


def _clean_name(value: Any) -> str:
    return _NAME_RE.sub("", str(value or "").strip())[:80]


def clean_event(raw: Any, now: float) -> Optional[dict]:
    """One validated event dict, or None when the input is unusable."""
    if not isinstance(raw, dict):
        return None
    etype = str(raw.get("type") or "").strip()
    if etype not in EVENT_TYPES:
        return None
    visit_id = _clean_id(raw.get("visit_id"))
    if not visit_id:
        return None
    ts = raw.get("ts")
    if isinstance(ts, (int, float)) and ts > 1e12:  # milliseconds (Date.now())
        ts = ts / 1000.0
    if not isinstance(ts, (int, float)) or abs(float(ts) - now) > _CLIENT_CLOCK_SKEW:
        ts = now
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = None
    else:
        value = max(0.0, min(float(value), MAX_HEARTBEAT_SECONDS if etype == "heartbeat" else 86400.0))
    return {
        "event_id": _clean_id(raw.get("id")),
        "ts": float(ts),
        "visit_id": visit_id,
        "chat_session_id": _clean_id(raw.get("chat_session_id")),
        "event_type": etype,
        "url_path": _clean_path(raw.get("path")),
        "event_name": _clean_name(raw.get("name")) if etype == "click" else "",
        "value": value,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def cohort_for(user_id: str) -> str:
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT cohort FROM invited_accounts WHERE user_id = ? LIMIT 1", (user_id,)
            )
            row = await cursor.fetchone()
        return str(row[0] or "") if row else ""
    except Exception:
        return ""  # no invited accounts table on this deployment


async def record_events(events: Iterable[dict], *, user_id: str, role: str, env: str,
                        cohort: str = "") -> int:
    """Insert validated events. Returns rows written (duplicates ignored)."""
    rows = [
        (e["event_id"], e["ts"], utc_day(e["ts"]), env, user_id, role, cohort, e["visit_id"],
         e["chat_session_id"], e["event_type"], e["url_path"], e["event_name"], e["value"])
        for e in events
    ]
    if not rows:
        return 0
    await init_telemetry_table()
    async with get_db() as db:
        before = db.total_changes
        await db.executemany(
            "INSERT OR IGNORE INTO ui_events (event_id, ts, day, env, user_id, role, cohort, visit_id, "
            "chat_session_id, event_type, url_path, event_name, value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        await db.commit()
        return db.total_changes - before


# ---------------------------------------------------------------------------
# Read (admin)
# ---------------------------------------------------------------------------

def user_key(user_id: str) -> str:
    """Stable pseudonym for an account (keyed hash; not reversible by
    hashing a guessed e-mail without the deployment secret)."""
    digest = hmac.new(_config.JWT_SECRET.encode(), (user_id or "").encode(), hashlib.sha256)
    return "u-" + digest.hexdigest()[:10]


async def _collect(days: int, now: Optional[float]) -> dict:
    now = now if now is not None else time.time()
    days = max(1, min(int(days), 366))
    start = utc_day_start(now) - (days - 1) * 86400
    await init_telemetry_table()
    await init_usage_table()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT ts, day, user_id, role, cohort, visit_id, event_type, event_name, value "
            "FROM ui_events WHERE ts >= ? ORDER BY ts",
            (start,),
        )
        events = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT day, user_id, role, COUNT(*), COALESCE(SUM(turn_cost_usd), 0) "
            "FROM usage_events WHERE ts >= ? GROUP BY day, user_id, role",
            (start,),
        )
        questions = await cursor.fetchall()
        cohorts: dict[str, str] = {}
        try:
            cursor = await db.execute("SELECT user_id, cohort FROM invited_accounts WHERE cohort != ''")
            cohorts = {str(u): str(c) for u, c in await cursor.fetchall()}
        except Exception:
            pass
    return {"start": start, "now": now, "days": days, "events": events,
            "questions": questions, "cohorts": cohorts}


def _visit_minutes(first: float, last: float, engaged_seconds: float) -> float:
    """Session length of one visit: wall time between its first and last
    event, but at least the engaged time reported by heartbeats."""
    return max(last - first, engaged_seconds) / 60.0


def _aggregate(data: dict) -> dict[tuple[str, str], dict]:
    """(day, user_id) -> per-user-day metrics."""
    cells: dict[tuple[str, str], dict] = {}
    visits: dict[tuple[str, str], dict] = {}

    def cell(day, uid, role, cohort):
        c = cells.setdefault((day, uid), {
            "date": day, "user_id": uid, "role": role or "", "cohort": cohort or "",
            "questions": 0, "cost_usd": 0.0, "page_views": 0, "clicks": 0,
            "visits": 0, "session_minutes": [], "targets": {},
        })
        if role and not c["role"]:
            c["role"] = role
        if cohort and not c["cohort"]:
            c["cohort"] = cohort
        return c

    for ts, day, uid, role, cohort, visit_id, etype, name, value in data["events"]:
        cohort = cohort or data["cohorts"].get(uid, "")
        c = cell(day, uid, role, cohort)
        if etype == "page_view":
            c["page_views"] += 1
        elif etype == "click":
            c["clicks"] += 1
            key = name or "untagged"
            c["targets"][key] = c["targets"].get(key, 0) + 1
        v = visits.setdefault((uid, visit_id), {"day": day, "uid": uid, "first": ts, "last": ts, "engaged": 0.0})
        v["last"] = max(v["last"], ts)
        if etype == "heartbeat" and value:
            v["engaged"] += float(value)

    for v in visits.values():
        c = cells[(v["day"], v["uid"])]
        c["visits"] += 1
        c["session_minutes"].append(_visit_minutes(v["first"], v["last"], v["engaged"]))

    for day, uid, role, n, cost in data["questions"]:
        c = cell(day, uid, role, data["cohorts"].get(uid, ""))
        c["questions"] += int(n)
        c["cost_usd"] += float(cost or 0.0)
    return cells


def _finish(c: dict) -> dict:
    mins = c["session_minutes"]
    return {
        "date": c["date"],
        "user_key": user_key(c["user_id"]),
        "role": c["role"],
        "cohort": c["cohort"],
        "questions": c["questions"],
        "cost_usd": round(c["cost_usd"], 4),
        "visits": c["visits"],
        "page_views": c["page_views"],
        "clicks": c["clicks"],
        "session_minutes_total": round(sum(mins), 1),
        "session_minutes_avg": round(statistics.mean(mins), 1) if mins else 0.0,
    }


async def engagement_summary(days: int, now: Optional[float] = None) -> dict[str, Any]:
    """Questions, clicks and session length per day, per user and per cohort."""
    data = await _collect(days, now)
    cells = _aggregate(data)

    daily = []
    for i in range(data["days"]):
        day = utc_day(data["start"] + i * 86400 + 1)
        day_cells = [c for (d, _), c in cells.items() if d == day]
        mins = [m for c in day_cells for m in c["session_minutes"]]
        daily.append({
            "date": day,
            "users": len({c["user_id"] for c in day_cells}),
            "visits": sum(c["visits"] for c in day_cells),
            "page_views": sum(c["page_views"] for c in day_cells),
            "clicks": sum(c["clicks"] for c in day_cells),
            "questions": sum(c["questions"] for c in day_cells),
            "session_minutes_avg": round(statistics.mean(mins), 1) if mins else 0.0,
        })

    by_user: dict[str, dict] = {}
    for c in cells.values():
        u = by_user.setdefault(c["user_id"], {
            "user_key": user_key(c["user_id"]), "role": c["role"], "cohort": c["cohort"],
            "days_active": 0, "questions": 0, "cost_usd": 0.0, "visits": 0, "page_views": 0,
            "clicks": 0, "_mins": [], "last_seen": c["date"],
        })
        u["days_active"] += 1
        for k in ("questions", "visits", "page_views", "clicks"):
            u[k] += c[k]
        u["cost_usd"] += c["cost_usd"]
        u["_mins"].extend(c["session_minutes"])
        u["last_seen"] = max(u["last_seen"], c["date"])
        u["role"] = u["role"] or c["role"]
        u["cohort"] = u["cohort"] or c["cohort"]
    users = []
    for u in by_user.values():
        mins = u.pop("_mins")
        u["cost_usd"] = round(u["cost_usd"], 4)
        u["session_minutes_avg"] = round(statistics.mean(mins), 1) if mins else 0.0
        u["session_minutes_total"] = round(sum(mins), 1)
        users.append(u)
    users.sort(key=lambda u: (-u["questions"], -u["clicks"], u["user_key"]))

    by_cohort: dict[str, dict] = {}
    for u in users:
        name = u["cohort"] or "(no cohort)"
        b = by_cohort.setdefault(name, {"cohort": name, "users": 0, "questions": 0, "visits": 0,
                                        "clicks": 0, "session_minutes_total": 0.0})
        b["users"] += 1
        b["questions"] += u["questions"]
        b["visits"] += u["visits"]
        b["clicks"] += u["clicks"]
        b["session_minutes_total"] += u["session_minutes_total"]
    cohorts = []
    for b in by_cohort.values():
        b["session_minutes_avg"] = round(b["session_minutes_total"] / b["visits"], 1) if b["visits"] else 0.0
        b["session_minutes_total"] = round(b["session_minutes_total"], 1)
        cohorts.append(b)
    cohorts.sort(key=lambda b: (-b["questions"], b["cohort"]))

    targets: dict[str, int] = {}
    for c in cells.values():
        for k, n in c["targets"].items():
            targets[k] = targets.get(k, 0) + n
    top = sorted(targets.items(), key=lambda kv: (-kv[1], kv[0]))[:25]

    all_mins = [m for c in cells.values() for m in c["session_minutes"]]
    return {
        "from": utc_day(data["start"]),
        "to": utc_day(data["now"]),
        "days": data["days"],
        "totals": {
            "users": len(by_user),
            "visits": sum(d["visits"] for d in daily),
            "page_views": sum(d["page_views"] for d in daily),
            "clicks": sum(d["clicks"] for d in daily),
            "questions": sum(d["questions"] for d in daily),
            "session_minutes_avg": round(statistics.mean(all_mins), 1) if all_mins else 0.0,
            "session_minutes_median": round(statistics.median(all_mins), 1) if all_mins else 0.0,
        },
        "daily": daily,
        "by_user": users,
        "by_cohort": cohorts,
        "top_targets": [{"name": k, "clicks": n} for k, n in top],
        "events_since": await _first_event_iso(),
    }


async def _first_event_iso() -> Optional[str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT MIN(ts) FROM ui_events")
        row = await cursor.fetchone()
    if not row or row[0] is None:
        return None
    return datetime.fromtimestamp(float(row[0]), tz=timezone.utc).isoformat(timespec="seconds")


CSV_COLUMNS = (
    "environment", "date", "user_key", "role", "cohort", "questions", "cost_usd", "visits",
    "page_views", "clicks", "session_minutes_total", "session_minutes_avg",
)


async def engagement_csv_rows(days: int, now: Optional[float] = None) -> list[dict]:
    """One row per (day, user): the regular review export."""
    data = await _collect(days, now)
    rows = [_finish(c) for c in _aggregate(data).values()]
    rows.sort(key=lambda r: (r["date"], r["cohort"], r["user_key"]))
    return rows


def log_dropped(reason: str, count: int) -> None:
    if count:
        logger.debug("Telemetry: dropped %d event(s): %s", count, reason)
