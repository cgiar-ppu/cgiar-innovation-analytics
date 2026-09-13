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
        await db.commit()


async def create_invitation(email: str, name: str, invited_by: str) -> str:
    token = secrets.token_urlsafe(32)
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("INSERT OR IGNORE INTO invited_accounts (email,user_id,name,created_at) VALUES (?,?,?,?)",
                         (email, "invited:" + str(uuid.uuid4()), name, time.time()))
        # Reissue replaces only the outstanding invitation, not an active password.
        await db.execute("DELETE FROM account_invitations WHERE email=?", (email,))
        await db.execute("INSERT INTO account_invitations VALUES (?,?,?,?)",
                         (token_hash(token), email, time.time() + 7 * 86400, invited_by))
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
    return {"user_id": row["user_id"], "email": row["email"], "name": row["name"],
            "role": "researcher", "credential_version": row["credential_version"]}


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
          a.password_hash IS NOT NULL AS activated,i.expires_at
          FROM invited_accounts a LEFT JOIN account_invitations i ON i.email=a.email
          ORDER BY a.created_at DESC""")).fetchall()
    return [dict(r) for r in rows]


async def revoke(email: str):
    async with get_db() as db:
        await db.execute("UPDATE invited_accounts SET enabled=0,credential_version=credential_version+1 WHERE email=?", (email,))
        await db.execute("DELETE FROM account_invitations WHERE email=?", (email,))
        await db.commit()
