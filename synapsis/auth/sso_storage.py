"""Encrypted, expiring OAuth state and explicit stable application identity links."""
import base64
import hashlib
import json
import secrets
import time
import uuid

from cryptography.fernet import Fernet

from synapsis import config
from synapsis.database.connection import get_db


def cipher() -> Fernet:
    key = hashlib.sha256(("ia-sso-v1:" + config.JWT_SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def init_sso_tables():
    async with get_db() as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS sso_sessions (
            key_hash TEXT PRIMARY KEY, kind TEXT NOT NULL,
            payload BLOB NOT NULL, expires_at REAL NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS sso_identities (
            issuer TEXT NOT NULL, subject TEXT NOT NULL,
            user_id TEXT NOT NULL UNIQUE, email TEXT NOT NULL, name TEXT NOT NULL,
            legacy INTEGER NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY (issuer, subject))""")
        await db.commit()


async def put_session(kind: str, payload: dict, lifetime: int) -> str:
    key = secrets.token_urlsafe(32)
    async with get_db() as db:
        await db.execute("DELETE FROM sso_sessions WHERE expires_at < ?", (time.time(),))
        await db.execute("INSERT INTO sso_sessions VALUES (?, ?, ?, ?)", (
            digest(key), kind, cipher().encrypt(json.dumps(payload).encode()), time.time() + lifetime,
        ))
        await db.commit()
    return key


async def get_session(key: str, kind: str, consume: bool = False) -> dict | None:
    if not key or len(key) > 128:
        return None
    async with get_db() as db:
        # DELETE RETURNING makes login transactions single-use even across workers.
        sql = ("DELETE FROM sso_sessions WHERE key_hash=? AND kind=? AND expires_at>? RETURNING payload"
               if consume else "SELECT payload FROM sso_sessions WHERE key_hash=? AND kind=? AND expires_at>?")
        cursor = await db.execute(sql, (digest(key), kind, time.time()))
        row = await cursor.fetchone()
        await db.commit()
    return json.loads(cipher().decrypt(row["payload"])) if row else None


async def update_session(key: str, payload: dict):
    async with get_db() as db:
        await db.execute("UPDATE sso_sessions SET payload=? WHERE key_hash=? AND expires_at>?", (
            cipher().encrypt(json.dumps(payload).encode()), digest(key), time.time(),
        ))
        await db.commit()


async def delete_session(key: str):
    async with get_db() as db:
        await db.execute("DELETE FROM sso_sessions WHERE key_hash=?", (digest(key),))
        await db.commit()


class LinkRequired(Exception):
    pass


async def resolve_identity(claims: dict, proven_legacy_email: str | None = None) -> dict:
    """Email alone NEVER attaches a Microsoft identity to an existing account.

    Legacy linking requires independently verified password ownership. A new
    researcher gets an opaque owner key; later email changes cannot change it.
    """
    issuer, subject, email = claims["iss"], claims["sub"], claims["email"]
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute("SELECT * FROM sso_identities WHERE issuer=? AND subject=?", (issuer, subject))
        link = await cursor.fetchone()
        if not link:
            cursor = await db.execute("SELECT email FROM users WHERE email=?", (email,))
            existing = await cursor.fetchone()
            if existing and proven_legacy_email != email:
                raise LinkRequired()
            user_id = email if existing else "sso:" + str(uuid.uuid4())
            await db.execute("INSERT INTO sso_identities VALUES (?, ?, ?, ?, ?, ?, ?)", (
                issuer, subject, user_id, email, str(claims.get("name", "")), bool(existing), time.time(),
            ))
            link = {"user_id": user_id, "legacy": bool(existing)}
        user = {"user_id": link["user_id"], "email": email,
                "name": str(claims.get("name", "")), "role": "researcher"}
        if link["legacy"]:
            cursor = await db.execute("SELECT email, name, role FROM users WHERE email=?", (link["user_id"],))
            existing = await cursor.fetchone()
            if not existing:
                raise ValueError("Linked application account is unavailable")
            user.update(dict(existing))
        await db.commit()
    return user
