"""
User authentication — DB-backed (interim self-signup, 2026-07-20).

Users now live in a persistent `users` table in chat.db (see
``synapsis/database/users.py``), not in the JSON allow-list at runtime. The
JSON allow-list (default: config/allowed_users.json) is still the *seed*
source for the baked-in accounts — it is loaded once at boot and upserted
into the table (never overwriting an existing row) — but is no longer read
on the login/signup hot path. Adding a baked-in user is still a config-file
edit (it seeds on next boot); the DB is what makes runtime self-signup
possible without a redeploy.

File format (unchanged):
{
  "users": [
    {
      "email": "user@cgiar.org",
      "name": "Full Name",
      "role": "admin|researcher|user",
      "password_hash": "$2b$12$..."
    }
  ]
}

Ported from ast-chatbot/synapsis/auth/users.py; extended for DB-backed storage.
"""

import json
from typing import Optional

import bcrypt

from synapsis.config import USERS_FILE, logger


def _load_allowed_users_json() -> list[dict]:
    """Load the baked-in allow-list JSON.

    Used only by the one-time (idempotent, re-run-safe) DB seed migration in
    ``synapsis.database.users.init_users_table`` — no longer on the login path.
    """
    if not USERS_FILE.exists():
        logger.warning("Users file not found at %s — no baked-in users to seed", USERS_FILE)
        return []

    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
        return data.get("users", [])
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Failed to load users file %s: %s", USERS_FILE, e)
        return []


async def get_user_by_email(email: str) -> Optional[dict]:
    """Look up a user by email address (case-insensitive) from the DB."""
    from synapsis.database.users import get_user_row
    return await get_user_row(email)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt for storage in the users table."""
    return bcrypt.hashpw(
        plain_password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


async def authenticate_user(email: str, password: str) -> Optional[dict]:
    """Authenticate a user by email and password.

    Returns a user dict (without password_hash) on success, None on failure.
    The returned dict includes ``user_id`` — the stable identity claim that
    every downstream consumer keys on (currently the email; the Cognito ``sub``
    once SSO federates).
    """
    user = await get_user_by_email(email)
    if not user:
        logger.info("Login attempt for unknown email: %s", email)
        return None

    password_hash = user.get("password_hash", "")
    if not password_hash or not verify_password(password, password_hash):
        logger.info("Failed login for: %s", email)
        return None

    logger.info("Successful login for: %s", email)
    return {
        "user_id": user["email"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role", "user"),
    }


async def list_users() -> list[dict]:
    """List all users (without password hashes)."""
    from synapsis.database.users import list_user_rows
    rows = await list_user_rows()
    return [
        {
            "user_id": r.get("email", ""),
            "email": r.get("email", ""),
            "name": r.get("name", ""),
            "role": r.get("role", "user"),
        }
        for r in rows
    ]
