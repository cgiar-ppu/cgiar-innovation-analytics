"""Answer and voice feedback from test users (Jules, 24 Sep 2026: restricted test group).

One row per user per rated item, editable:

- ``channel='chat'``: a finished chat answer. ``session_id`` is the chat,
  ``message_id`` is ``r<k>`` = the k-th finished answer (``result`` row) of that
  chat. The ordinal is stable across live streaming and a history reload,
  unlike the browser's message ids.
- ``channel='voice'``: a voice-guide session. ``session_id`` is the voice
  request id, ``message_id`` is ``''``.
- ``channel='general'`` (MVP test release, 14 Oct 2026): the global "Give
  feedback" form available on every page. Every submission is a new row
  (``session_id`` = ``g-<random>``, ``message_id`` = ``''``, ``rating`` = 0)
  with a ``category`` (stuck / wrong_result / inappropriate_inaccurate /
  other), the page it was sent from, and, when the user was in a chat, that
  chat's id and the latest answer ordinal (``chat_id``/``answer_id``; ids
  only, never chat text). An optional screenshot is stored as a file next to
  the database (``feedback-attachments/<random>.png|jpg``); the row keeps
  only that relative path (``attachment_path``), never the image bytes.

Privacy (Jose's 2026-09-14 rule: administrators never read other users' chats):
the question and answer text are copied into this table ONLY when the user
ticks "share this question and answer" (``shared_question``/``shared_answer``).
Otherwise an administrator sees the rating, the user's own comment and the
metadata (model, specialist, data scope, app version, environment, cohort),
never chat content. Nothing here is forwarded to Slack or email.

Writes use short-lived connections (``get_db``), like the usage ledger, so a
cancelled request can never leave a transaction open on the shared connection.
"""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

import synapsis.config as _config
from synapsis.config import logger
from synapsis.database.connection import get_db

CHANNELS = ("chat", "voice", "general")
#: Categories of the general "Give feedback" form (MVP test release requirements, 9 Oct 2026:
#: "flag when they are stuck, when a result looks wrong, or when the tool is
#: inappropriate/inaccurate").
CATEGORIES = ("stuck", "wrong_result", "inappropriate_inaccurate", "other")
CATEGORY_LABELS = {
    "stuck": "I'm stuck",
    "wrong_result": "This result looks wrong",
    "inappropriate_inaccurate": "Inappropriate or inaccurate",
    "other": "Other",
}
ANSWER_ID = re.compile(r"^r([1-9][0-9]{0,5})$")
MAX_SHARED_QUESTION = 2000
MAX_SHARED_ANSWER = 8000

_READY_PATHS: set[str] = set()

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS answer_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        session_id TEXT NOT NULL,
        message_id TEXT NOT NULL DEFAULT '',
        rating INTEGER NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        expected TEXT NOT NULL DEFAULT '',
        shared_question TEXT,
        shared_answer TEXT,
        model TEXT NOT NULL DEFAULT '',
        persona TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT '',
        cohort TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        environment TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE (user_id, channel, session_id, message_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_feedback_created ON answer_feedback (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_session ON answer_feedback (user_id, session_id)",
)

#: Migration ``answer_feedback_general_v1`` (14 Oct 2026): columns for the
#: general feedback form. Older databases upgrade in place (SQLite only allows
#: ADD COLUMN); '' = not applicable (chat/voice rows).
MIGRATION_NAME = "answer_feedback_general_v1"
_ADDED_COLUMNS = (
    ("category", "TEXT NOT NULL DEFAULT ''"),
    ("attachment_path", "TEXT NOT NULL DEFAULT ''"),
    ("page", "TEXT NOT NULL DEFAULT ''"),
    ("chat_id", "TEXT NOT NULL DEFAULT ''"),
    ("answer_id", "TEXT NOT NULL DEFAULT ''"),
)

# Screenshot attachments: PNG or JPEG only, at most 5 MB, stored as files.
ATTACHMENT_DIR = "feedback-attachments"
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_ATTACHMENT_NAME = re.compile(r"^feedback-attachments/([0-9a-f]{32})\.(png|jpg)$")
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"))


async def init_feedback_table() -> None:
    """Create the feedback table if needed (idempotent, cached per DB path)."""
    path = str(_config.DB_PATH)
    if path in _READY_PATHS:
        return
    async with get_db() as db:
        for stmt in _SCHEMA:
            await db.execute(stmt)
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(answer_feedback)")).fetchall()}
        for name, kind in _ADDED_COLUMNS:
            if name not in columns:
                await db.execute(f"ALTER TABLE answer_feedback ADD COLUMN {name} {kind}")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_user_created ON answer_feedback (user_id, channel, created_at)")
        await db.commit()
    _READY_PATHS.add(path)


# ---------------------------------------------------------------------------
# Screenshot attachments (general feedback)
# ---------------------------------------------------------------------------

def image_kind(data: bytes) -> Optional[str]:
    """'png' / 'jpg' from the file's own signature (the browser's type is not trusted)."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    return None


def attachments_dir() -> Path:
    """Folder next to the database (``.synapsis/``), never served by /api/files."""
    return Path(_config.DB_PATH).parent / ATTACHMENT_DIR


def save_attachment(data: bytes, kind: str) -> str:
    """Write the image under an unguessable name; returns the stored relative path."""
    if kind not in ("png", "jpg"):
        raise ValueError("unsupported image type")
    folder = attachments_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{kind}"
    (folder / name).write_bytes(data)
    return f"{ATTACHMENT_DIR}/{name}"


def attachment_file(rel: str) -> Optional[Path]:
    """Absolute path of a stored attachment, or None (bad name or missing file)."""
    match = _ATTACHMENT_NAME.match(rel or "")
    if not match:
        return None
    path = attachments_dir() / f"{match.group(1)}.{match.group(2)}"
    return path if path.is_file() else None


def remove_attachment(rel: str) -> None:
    path = attachment_file(rel)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# What is being rated
# ---------------------------------------------------------------------------

def _loads(data: str) -> dict:
    try:
        value = json.loads(data)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def answer_context(session_id: str, ordinal: int) -> Optional[dict[str, Any]]:
    """The k-th finished answer of a chat: question, answer text, turn metadata.

    ``None`` when the chat has fewer than ``ordinal`` finished answers. The
    caller has already checked that the chat belongs to the user.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT ts, type, data FROM messages WHERE session_id = ? "
            "AND type IN ('user', 'text', 'result') ORDER BY ts, id",
            (session_id,),
        )
        rows = await cursor.fetchall()
        question: dict = {}
        texts: list[str] = []
        seen = 0
        found: Optional[dict[str, Any]] = None
        for ts, kind, data in rows:
            payload = _loads(data)
            if kind == "user":
                question = payload
                texts = []
            elif kind == "text":
                content = payload.get("content")
                if isinstance(content, str) and content.strip():
                    texts.append(content)
            else:  # result
                seen += 1
                if seen == ordinal:
                    answer = "\n\n".join(texts)
                    if not answer and isinstance(payload.get("result_text"), str):
                        answer = payload["result_text"]
                    found = {
                        "result_ts": float(ts),
                        "question": str(question.get("content") or ""),
                        "answer": answer,
                        "persona": question.get("agent") if isinstance(question.get("agent"), str) else "",
                        "scope": question.get("scope") if isinstance(question.get("scope"), dict) else None,
                        "is_error": bool(payload.get("is_error")),
                    }
                    break
                texts = []
        if found is None:
            return None
        found["model"] = await _model_for_answer(db, session_id, found["result_ts"])
    return found


async def _model_for_answer(db: aiosqlite.Connection, session_id: str, result_ts: float) -> str:
    """Model of that answer from the usage ledger, else the chat's model."""
    try:
        cursor = await db.execute(
            "SELECT model FROM usage_events WHERE session_id = ? AND ts BETWEEN ? AND ? "
            "ORDER BY ABS(ts - ?) LIMIT 1",
            (session_id, result_ts - 5, result_ts + 120, result_ts),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return str(row[0])
    except aiosqlite.OperationalError:
        pass  # ledger table not created yet on this database
    cursor = await db.execute("SELECT model FROM sessions WHERE session_id = ?", (session_id,))
    row = await cursor.fetchone()
    return str(row[0] or "") if row else ""


async def voice_session_exists(owner: str, request_id: str) -> bool:
    """True if ``owner`` really started this voice session (not a close tombstone)."""
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT 1 FROM voice_sessions WHERE owner = ? AND request_id = ? AND sdp_hash != ''",
                (owner, request_id),
            )
            return await cursor.fetchone() is not None
    except aiosqlite.OperationalError:
        return False


async def cohort_for(user_id: str) -> str:
    """Test cohort of an invited account ('' for SSO/other users)."""
    if not user_id.startswith("invited:"):
        return ""
    try:
        async with get_db() as db:
            cursor = await db.execute("SELECT cohort FROM invited_accounts WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
    except aiosqlite.OperationalError:
        return ""
    return str(row[0] or "") if row else ""


# ---------------------------------------------------------------------------
# Owner reads/writes
# ---------------------------------------------------------------------------

_OWN_COLUMNS = ("id", "channel", "session_id", "message_id", "rating", "comment", "expected",
                "shared_question", "created_at", "updated_at")


def _own_view(row: dict) -> dict:
    out = {k: row[k] for k in _OWN_COLUMNS if k in row}
    out["share_answer"] = row.get("shared_question") is not None
    out.pop("shared_question", None)
    if row.get("channel") == "general":
        out.update({
            "category": row.get("category", ""),
            "page": row.get("page", ""),
            "chat_id": row.get("chat_id", ""),
            "answer_id": row.get("answer_id", ""),
            "has_attachment": bool(row.get("attachment_path")),
        })
    return out


async def upsert_feedback(
    *,
    user_id: str,
    channel: str,
    session_id: str,
    message_id: str,
    rating: int,
    comment: str = "",
    expected: str = "",
    shared_question: Optional[str] = None,
    shared_answer: Optional[str] = None,
    model: str = "",
    persona: str = "",
    scope: str = "",
    role: str = "",
    cohort: str = "",
    app_version: str = "",
    environment: str = "",
    now: Optional[float] = None,
) -> dict:
    """Insert or edit the caller's single feedback row for this item."""
    await init_feedback_table()
    now = now if now is not None else time.time()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO answer_feedback (user_id, channel, session_id, message_id, rating,
                   comment, expected, shared_question, shared_answer, model, persona, scope,
                   role, cohort, app_version, environment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id, channel, session_id, message_id) DO UPDATE SET
                   rating = excluded.rating, comment = excluded.comment,
                   expected = excluded.expected, shared_question = excluded.shared_question,
                   shared_answer = excluded.shared_answer, model = excluded.model,
                   persona = excluded.persona, scope = excluded.scope, role = excluded.role,
                   cohort = excluded.cohort, environment = excluded.environment,
                   updated_at = excluded.updated_at""",
            (user_id, channel, session_id, message_id, int(rating), comment, expected,
             shared_question, shared_answer, model or "", persona or "", scope or "",
             role or "", cohort or "", app_version or "", environment or "", now, now),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM answer_feedback WHERE user_id = ? AND channel = ? AND session_id = ? AND message_id = ?",
            (user_id, channel, session_id, message_id),
        )
        row = dict(await cursor.fetchone())
    return _own_view(row)


async def insert_general_feedback(
    *,
    user_id: str,
    category: str,
    comment: str = "",
    page: str = "",
    chat_id: str = "",
    answer_id: str = "",
    attachment_path: str = "",
    model: str = "",
    persona: str = "",
    scope: str = "",
    role: str = "",
    cohort: str = "",
    app_version: str = "",
    environment: str = "",
    now: Optional[float] = None,
) -> dict:
    """Store one general feedback submission (a new row every time)."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    await init_feedback_table()
    now = now if now is not None else time.time()
    session_id = "g-" + secrets.token_hex(12)
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO answer_feedback (user_id, channel, session_id, message_id, rating,
                   comment, expected, shared_question, shared_answer, model, persona, scope,
                   role, cohort, app_version, environment, created_at, updated_at,
                   category, attachment_path, page, chat_id, answer_id)
               VALUES (?, 'general', ?, '', 0, ?, '', NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, session_id, comment, model or "", persona or "", scope or "", role or "",
             cohort or "", app_version or "", environment or "", now, now,
             category, attachment_path or "", page or "", chat_id or "", answer_id or ""),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM answer_feedback WHERE id = ?", (cursor.lastrowid,))
        row = dict(await cursor.fetchone())
    return _own_view(row)


async def recent_general_count(user_id: str, since: float) -> int:
    """How many general submissions ``user_id`` made since ``since`` (rate limit)."""
    await init_feedback_table()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM answer_feedback WHERE user_id = ? AND channel = 'general' AND created_at >= ?",
            (user_id, since))
        return int((await cursor.fetchone())[0])


async def get_feedback_row(feedback_id: int) -> Optional[dict]:
    """One row by id (admin attachment download)."""
    await init_feedback_table()
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM answer_feedback WHERE id = ?", (feedback_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


async def own_feedback(user_id: str, session_id: str, channel: str = "chat") -> list[dict]:
    await init_feedback_table()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM answer_feedback WHERE user_id = ? AND session_id = ? AND channel = ? ORDER BY id",
            (user_id, session_id, channel),
        )
        return [_own_view(dict(r)) for r in await cursor.fetchall()]


async def delete_own_feedback(user_id: str, feedback_id: int) -> bool:
    await init_feedback_table()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT attachment_path FROM answer_feedback WHERE id = ? AND user_id = ?", (feedback_id, user_id))
        row = await cursor.fetchone()
        cursor = await db.execute(
            "DELETE FROM answer_feedback WHERE id = ? AND user_id = ?", (feedback_id, user_id))
        await db.commit()
        deleted = cursor.rowcount == 1
    if deleted and row and row[0]:
        remove_attachment(str(row[0]))
    return deleted


# ---------------------------------------------------------------------------
# Admin view
# ---------------------------------------------------------------------------

SENTIMENT_SQL = {
    # chat: +1 / -1; voice: 1..5 (4-5 positive, 3 neutral, 1-2 negative)
    "positive": "((f.channel = 'chat' AND f.rating > 0) OR (f.channel = 'voice' AND f.rating >= 4))",
    "negative": "((f.channel = 'chat' AND f.rating < 0) OR (f.channel = 'voice' AND f.rating <= 2))",
    "neutral": "(f.channel = 'voice' AND f.rating = 3)",
}
NO_COHORT = "__none__"


def sentiment(channel: str, rating: int) -> str:
    """positive / negative / neutral for ratings; '' for general feedback (no rating)."""
    if channel == "general":
        return ""
    if channel == "chat":
        return "positive" if rating > 0 else "negative"
    return "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"


def _day_start(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


async def _user_labels(db: aiosqlite.Connection) -> dict[str, dict[str, str]]:
    """user_id -> {email, name} for admin display (admin-only endpoint)."""
    labels: dict[str, dict[str, str]] = {}
    for sql in (
        "SELECT email, email, name FROM users",
        "SELECT user_id, email, name FROM sso_identities",
        "SELECT user_id, email, name FROM invited_accounts",
    ):
        try:
            cursor = await db.execute(sql)
            for uid, email, name in await cursor.fetchall():
                labels[str(uid)] = {"email": str(email or ""), "name": str(name or "")}
        except aiosqlite.OperationalError:
            continue
    return labels


async def list_feedback(
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    rating: Optional[str] = None,
    cohort: Optional[str] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """All users' feedback for administrators, newest first, with filters."""
    await init_feedback_table()
    where, args = ["1 = 1"], []
    if date_from:
        where.append("f.created_at >= ?")
        args.append(_day_start(date_from))
    if date_to:
        where.append("f.created_at < ?")
        args.append(_day_start(date_to) + 86400)
    if rating:
        where.append(SENTIMENT_SQL[rating])
    if cohort is not None and cohort != "":
        if cohort == NO_COHORT:
            where.append("f.cohort = ''")
        else:
            where.append("f.cohort = ?")
            args.append(cohort)
    if channel:
        where.append("f.channel = ?")
        args.append(channel)
    if category:
        where.append("f.category = ?")
        args.append(category)
    sql_where = " AND ".join(where)
    async with get_db() as db:
        labels = await _user_labels(db)
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM answer_feedback f WHERE {sql_where}", tuple(args))
        total = int((await cursor.fetchone())[0])
        cursor = await db.execute(
            f"SELECT f.* FROM answer_feedback f WHERE {sql_where} "
            "ORDER BY f.created_at DESC, f.id DESC LIMIT ?",
            (*args, max(1, min(int(limit), 5000))),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT DISTINCT cohort FROM answer_feedback WHERE cohort != '' ORDER BY cohort")
        cohorts = {str(r[0]) for r in await cursor.fetchall()}
        try:
            cursor = await db.execute(
                "SELECT DISTINCT cohort FROM invited_accounts WHERE cohort != ''")
            cohorts |= {str(r[0]) for r in await cursor.fetchall()}
        except aiosqlite.OperationalError:
            pass
    items = []
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    by_category = {c: 0 for c in CATEGORIES}
    for row in rows:
        label = labels.get(row["user_id"], {})
        mood = sentiment(row["channel"], int(row["rating"]))
        if mood:
            counts[mood] += 1
        if row["channel"] == "general" and row.get("category") in by_category:
            by_category[row["category"]] += 1
        attachment = attachment_file(row.get("attachment_path") or "")
        items.append({
            "id": row["id"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "channel": row["channel"],
            "rating": int(row["rating"]),
            "sentiment": mood,
            "comment": row["comment"],
            "expected": row["expected"],
            "shared_question": row["shared_question"],
            "shared_answer": row["shared_answer"],
            "user_email": label.get("email", ""),
            "user_name": label.get("name", ""),
            "role": row["role"],
            "cohort": row["cohort"],
            "session_id": row["session_id"],
            "message_id": row["message_id"],
            "model": row["model"],
            "persona": row["persona"],
            "scope": row["scope"],
            "app_version": row["app_version"],
            "environment": row["environment"],
            "category": row.get("category") or "",
            "category_label": CATEGORY_LABELS.get(row.get("category") or "", ""),
            "page": row.get("page") or "",
            "chat_id": row.get("chat_id") or "",
            "answer_id": row.get("answer_id") or "",
            "has_attachment": attachment is not None,
            "attachment_type": attachment.suffix.lstrip(".") if attachment is not None else "",
            "attachment_url": f"/api/admin/feedback/{row['id']}/attachment" if attachment is not None else "",
        })
    return {"total": total, "returned": len(items), "counts": counts, "by_category": by_category,
            "cohorts": sorted(cohorts), "items": items}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")


CSV_COLUMNS = ("created_at", "updated_at", "channel", "rating", "sentiment", "comment", "expected",
               "shared_question", "shared_answer", "user_email", "user_name", "role", "cohort",
               "model", "persona", "scope", "app_version", "environment", "session_id", "message_id",
               # General feedback (answer_feedback_general_v1); empty for chat/voice ratings.
               "id", "category", "page", "chat_id", "answer_id", "screenshot")


def _cell(value: Any) -> str:
    """CSV cell safe to open in Excel (no formula execution)."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def screenshot_name(item: dict) -> str:
    """File name of an item's screenshot inside the ZIP export ('' if none)."""
    if not item.get("has_attachment"):
        return ""
    return f"screenshots/feedback-{item['id']}.{item.get('attachment_type') or 'png'}"


def to_csv(items: list[dict], *, in_zip: bool = False) -> str:
    """CSV of ``items``. ``screenshot`` is the admin download URL, or, inside
    the ZIP export, the image's file name next to the CSV."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for item in items:
        values = []
        for col in CSV_COLUMNS:
            if col == "category":
                value = item.get("category_label") or item.get("category")
            elif col == "screenshot":
                value = screenshot_name(item) if in_zip else item.get("attachment_url", "")
            else:
                value = item.get(col)
            values.append(_cell(value))
        writer.writerow(values)
    return out.getvalue()


async def to_zip(items: list[dict]) -> bytes:
    """``feedback.csv`` plus every screenshot under ``screenshots/`` (admin export)."""
    import zipfile

    ids = [int(i["id"]) for i in items if i.get("has_attachment")]
    paths: dict[int, str] = {}
    async with get_db() as db:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            cursor = await db.execute(
                f"SELECT id, attachment_path FROM answer_feedback WHERE id IN ({','.join('?' * len(chunk))})",
                tuple(chunk))
            paths.update({int(r[0]): str(r[1] or "") for r in await cursor.fetchall()})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feedback.csv", "\ufeff" + to_csv(items, in_zip=True))
        for item in items:
            name = screenshot_name(item)
            path = attachment_file(paths.get(int(item["id"]), "")) if name else None
            if path is not None:
                archive.write(path, name)
    return buffer.getvalue()


def log_saved(channel: str, rating: int, category: str = "", attachment: bool = False) -> None:
    """One log line without identities or text (comments may describe users' work)."""
    if channel == "general":
        logger.info("feedback_saved channel=general category=%s screenshot=%s", category, "yes" if attachment else "no")
        return
    logger.info("feedback_saved channel=%s rating=%s", channel, rating)
