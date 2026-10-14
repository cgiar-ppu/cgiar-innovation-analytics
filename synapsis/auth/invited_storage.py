"""Explicit invitations; legacy password records never grant invited access."""
import asyncio
import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import closing

from synapsis import config
from synapsis.database.connection import get_db
from synapsis.auth.users import hash_password, verify_password


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def init_invited_tables():
    async with get_db() as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS invited_accounts (
          email TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password_hash TEXT, enabled INTEGER NOT NULL DEFAULT 1,
          credential_version INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS account_invitations (
          token_hash TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
          expires_at REAL NOT NULL, invited_by TEXT NOT NULL)""")
        # Test-round cohort label (e.g. "WB TTLs Oct-2026"), added 2026-09-26.
        # Older databases upgrade in place; '' = no cohort.
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(invited_accounts)")).fetchall()}
        if "cohort" not in columns:
            await db.execute("ALTER TABLE invited_accounts ADD COLUMN cohort TEXT NOT NULL DEFAULT ''")
        # Access level, added 2026-10-14: 'researcher' (full analytic data, the
        # behaviour every existing invited account keeps) or 'external' (partner
        # view: no budget / financial figures, see synapsis/prms_access_policy.py).
        if "role" not in columns:
            await db.execute("ALTER TABLE invited_accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'researcher'")
        await db.commit()


DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30

#: Roles an invitation can grant. Never 'admin': administrators come from SSO.
INVITED_ROLES = ("researcher", "external")
DEFAULT_INVITED_ROLE = "researcher"


def _checked_role(role: str | None) -> str | None:
    if role is None:
        return None
    if role not in INVITED_ROLES:
        raise ValueError(f"Invited accounts can only be {' or '.join(INVITED_ROLES)}")
    return role


async def create_invitation(email: str, name: str, invited_by: str, cohort: str | None = None,
                            expires_days: int = DEFAULT_EXPIRY_DAYS, role: str | None = None) -> str:
    """One-use link for ``email``. ``cohort=None`` keeps an existing label; '' clears it.

    ``role=None`` keeps an existing account's access level (a new account gets
    ``DEFAULT_INVITED_ROLE``); 'researcher' / 'external' set it. Changing the
    level of an account also ends its current sign-ins (credential version),
    so an already-issued token can never keep the old level.
    """
    role = _checked_role(role)
    token = secrets.token_urlsafe(32)
    days = max(1, min(int(expires_days), MAX_EXPIRY_DAYS))
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("INSERT OR IGNORE INTO invited_accounts (email,user_id,name,created_at,cohort,role) VALUES (?,?,?,?,?,?)",
                         (email, "invited:" + str(uuid.uuid4()), name, time.time(), cohort or "",
                          role or DEFAULT_INVITED_ROLE))
        if cohort is not None:
            await db.execute("UPDATE invited_accounts SET cohort=? WHERE email=?", (cohort, email))
        if role is not None:
            await db.execute("""UPDATE invited_accounts SET role=?,credential_version=credential_version+1
              WHERE email=? AND role<>?""", (role, email, role))
        # Reissue replaces only the outstanding invitation, not an active password.
        await db.execute("DELETE FROM account_invitations WHERE email=?", (email,))
        await db.execute("INSERT INTO account_invitations VALUES (?,?,?,?)",
                         (token_hash(token), email, time.time() + days * 86400, invited_by))
        await db.commit()
    return token


async def inspect_invitation(token: str) -> dict | None:
    async with get_db() as db:
        row = await (await db.execute("""SELECT a.email,a.name,i.expires_at FROM account_invitations i
          JOIN invited_accounts a ON a.email=i.email WHERE i.token_hash=? AND i.expires_at>?""",
          (token_hash(token), time.time()))).fetchone()
    return dict(row) if row else None


async def accept_invitation(token: str, password: str) -> dict | None:
    hashed = await asyncio.to_thread(hash_password, password)
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute("DELETE FROM account_invitations WHERE token_hash=? AND expires_at>? RETURNING email",
                                     (token_hash(token), time.time()))).fetchone()
        if not row:
            return None
        await db.execute("""UPDATE invited_accounts SET password_hash=?,enabled=1,
          credential_version=credential_version+1 WHERE email=?""", (hashed, row["email"]))
        account = await (await db.execute("SELECT * FROM invited_accounts WHERE email=?", (row["email"],))).fetchone()
        await db.commit()
    return public_user(dict(account))


def public_user(row: dict) -> dict:
    role = row.get("role") or DEFAULT_INVITED_ROLE
    if role not in INVITED_ROLES:  # never more than researcher from this table
        role = DEFAULT_INVITED_ROLE
    return {"user_id": row["user_id"], "email": row["email"], "name": row["name"],
            "role": role, "credential_version": row["credential_version"]}


async def authenticate(email: str, password: str) -> dict | None:
    async with get_db() as db:
        row = await (await db.execute("SELECT * FROM invited_accounts WHERE email=? AND enabled=1",
                                     (email.lower().strip(),))).fetchone()
    if not row or not row["password_hash"]:
        return None
    if not await asyncio.to_thread(verify_password, password, row["password_hash"]):
        return None
    return public_user(dict(row))


def credential_is_current(user_id: str, version: int) -> bool:
    """Called by the shared sync verifier, including WebSocket handshakes.

    A fresh read ensures revocation/reset takes effect for issued tokens too.
    """
    try:
        with closing(sqlite3.connect(config.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute("SELECT enabled,credential_version FROM invited_accounts WHERE user_id=?",
                             (user_id,)).fetchone()
        return bool(row and row[0] and row[1] == version)
    except sqlite3.Error:
        return False


async def list_accounts() -> list[dict]:
    async with get_db() as db:
        rows = await (await db.execute("""SELECT a.email,a.name,a.enabled,
          a.password_hash IS NOT NULL AS activated,i.expires_at,a.cohort,a.role
          FROM invited_accounts a LEFT JOIN account_invitations i ON i.email=a.email
          ORDER BY a.created_at DESC""")).fetchall()
    return [dict(r) for r in rows]


async def revoke(email: str):
    async with get_db() as db:
        await db.execute("UPDATE invited_accounts SET enabled=0,credential_version=credential_version+1 WHERE email=?", (email,))
        await db.execute("DELETE FROM account_invitations WHERE email=?", (email,))
        await db.commit()


async def set_cohort(email: str, cohort: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute("UPDATE invited_accounts SET cohort=? WHERE email=?", (cohort, email))
        await db.commit()
        return cursor.rowcount == 1


async def set_role(email: str, role: str) -> bool:
    """Change an account's access level; ends its current sign-ins if it changed."""
    role = _checked_role(role)
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        exists = await (await db.execute("SELECT 1 FROM invited_accounts WHERE email=?", (email,))).fetchone()
        await db.execute("""UPDATE invited_accounts SET role=?,credential_version=credential_version+1
          WHERE email=? AND role<>?""", (role, email, role))
        await db.commit()
    return bool(exists)


async def revoke_cohort(cohort: str) -> int:
    """Revoke every account of a test cohort (end of a test round). Returns how many."""
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        emails = [r[0] for r in await (await db.execute(
            "SELECT email FROM invited_accounts WHERE cohort=? AND enabled=1", (cohort,))).fetchall()]
        await db.execute("DELETE FROM account_invitations WHERE email IN (SELECT email FROM invited_accounts WHERE cohort=?)", (cohort,))
        await db.execute("UPDATE invited_accounts SET enabled=0,credential_version=credential_version+1 WHERE cohort=?", (cohort,))
        await db.commit()
    return len(emails)
