"""User account persistence (interim self-signup, 2026-07-20).

Users used to live *only* in the baked-in JSON allow-list
(``config/allowed_users.json``), which is immutable at runtime (it ships
inside the Docker image). This module adds a persistent ``users`` table in
the same chat.db that already rides the existing litestream replication, so
new self-service accounts (see ``synapsis/auth/routes.py::signup``) survive
container/instance replacement exactly like chat history does.

Boot behaviour (``init_users_table``):
- Creates the table if missing.
- Idempotently seeds/upserts every user from the JSON allow-list, but NEVER
  overwrites an existing row's password hash — a user may already have
  signed up with the same email as a baked-in allow-list entry, and their
  chosen password must win.
"""

import time
from typing import Optional

from synapsis.config import logger
from synapsis.database.connection import get_db, _get_shared_db


async def init_users_table() -> None:
    """Create the `users` table if missing and seed it from the JSON allow-list.

    Safe to call on every boot: table creation is `CREATE TABLE IF NOT EXISTS`
    and the seed step uses `INSERT OR IGNORE` keyed on the email primary key,
    so re-running this never overwrites an existing row (including one a real
    user created via self-signup with the same email as a baked-in account).
    """
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'researcher',
                created_at REAL NOT NULL
            )
        """)
        await db.commit()

    await _seed_from_allowed_users_json()


async def _seed_from_allowed_users_json() -> None:
    """Idempotent boot migration: seed/upsert baked-in users into the table.

    Uses `INSERT OR IGNORE` so an already-present row (whether seeded on a
    prior boot, or created by a real self-signup that happens to share an
    email with a baked-in account) is left completely untouched.
    """
    # Local import to avoid a module-load cycle (synapsis.auth.users imports
    # synapsis.database.users for the DB-backed lookups).
    from synapsis.auth.users import _load_allowed_users_json

    allowed_users = _load_allowed_users_json()
    if not allowed_users:
        return

    db = await _get_shared_db()
    now = time.time()
    seeded = 0
    for u in allowed_users:
        email = (u.get("email") or "").lower().strip()
        password_hash = u.get("password_hash") or ""
        if not email or not password_hash:
            logger.warning("Skipping malformed allow-list entry (missing email/hash): %r", u)
            continue
        cursor = await db.execute(
            "INSERT OR IGNORE INTO users (email, name, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, u.get("name", ""), password_hash, u.get("role", "researcher"), now),
        )
        if cursor.rowcount:
            seeded += 1
    await db.commit()
    if seeded:
        logger.info("Seeded %d user(s) from the allow-list JSON into the users table", seeded)


async def get_user_row(email: str) -> Optional[dict]:
    """Look up a user row by email (case-insensitive). Includes password_hash."""
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT email, name, password_hash, role, created_at FROM users WHERE email = ?",
        (email.lower().strip(),),
    )
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def create_user_row(email: str, name: str, password_hash: str, role: str = "researcher") -> None:
    """Insert a brand-new user row.

    Callers MUST check :func:`get_user_row` first and return 409 on an
    existing email — this function does not itself guard against duplicates
    beyond the PRIMARY KEY constraint (which would raise ``IntegrityError``).
    """
    db = await _get_shared_db()
    await db.execute(
        "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (email.lower().strip(), name, password_hash, role, time.time()),
    )
    await db.commit()


async def list_user_rows() -> list[dict]:
    """List all users (without password hashes)."""
    db = await _get_shared_db()
    cursor = await db.execute(
        "SELECT email, name, role, created_at FROM users ORDER BY email"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
