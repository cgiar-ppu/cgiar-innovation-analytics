"""Encrypted, expiring OAuth state and stable CGIAR-only application identities."""
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
            role TEXT NOT NULL DEFAULT 'researcher', created_at REAL NOT NULL,
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


async def resolve_identity(claims: dict) -> dict:
    """Fresh CGIAR identities; never match or migrate password accounts.

    A stable opaque owner key is bound only to the verified issuer/subject.
    Roles are assigned in the application DB, never from external role claims.
    """
    issuer, subject, email = claims["iss"], claims["sub"], claims["email"]
    role = "admin" if subject in config.SSO_ADMIN_SUBJECTS else "researcher"
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute("SELECT user_id, role FROM sso_identities WHERE issuer=? AND subject=?", (issuer, subject))
        identity = await cursor.fetchone()
        if not identity:
            identity = {"user_id": "sso:" + str(uuid.uuid4()), "role": role}
            await db.execute("INSERT INTO sso_identities VALUES (?, ?, ?, ?, ?, ?, ?)", (
                issuer, subject, identity["user_id"], email, str(claims.get("name", "")), role, time.time(),
            ))
        else:
            await db.execute("UPDATE sso_identities SET role=? WHERE issuer=? AND subject=?", (role, issuer, subject))
        await db.commit()
    return {"user_id": identity["user_id"], "email": email,
            "name": str(claims.get("name", "")), "role": role}
