"""
User management from a JSON allow-list file.

Users are defined in a JSON config file (default: config/allowed_users.json).
Adding or removing users is a config-file edit — no code changes needed.

File format:
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

Ported from ast-chatbot/synapsis/auth/users.py.
"""

import json
from typing import Optional

import bcrypt

from synapsis.config import USERS_FILE, logger


def _load_users() -> list[dict]:
    """Load users from the JSON allow-list file."""
    if not USERS_FILE.exists():
        logger.warning("Users file not found at %s — no password users can log in", USERS_FILE)
        return []

    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
        return data.get("users", [])
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Failed to load users file %s: %s", USERS_FILE, e)
        return []


def get_user_by_email(email: str) -> Optional[dict]:
    """Look up a user by email address (case-insensitive)."""
    users = _load_users()
    email_lower = email.lower().strip()
    for user in users:
        if user.get("email", "").lower().strip() == email_lower:
            return user
    return None


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
    """Hash a password with bcrypt for storage in the users file."""
    return bcrypt.hashpw(
        plain_password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def authenticate_user(email: str, password: str) -> Optional[dict]:
    """Authenticate a user by email and password.

    Returns a user dict (without password_hash) on success, None on failure.
    The returned dict includes ``user_id`` — the stable identity claim that
    every downstream consumer keys on (currently the email; the Cognito ``sub``
    once SSO federates).
    """
    user = get_user_by_email(email)
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


def list_users() -> list[dict]:
    """List all users (without password hashes)."""
    users = _load_users()
    return [
        {
            "user_id": u.get("email", ""),
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "role": u.get("role", "user"),
        }
        for u in users
    ]
