"""
JWT token creation and validation.

Ported from ast-chatbot/synapsis/auth/tokens.py.

The token payload's ``sub`` is the stable application identity. Legacy users
keep their email owner key after explicit SSO linking; new SSO users get an
opaque application ID. Cognito subjects are never substituted for owner keys.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from synapsis.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS, logger


def create_access_token(user_id: str, user_name: str, user_role: str,
                        *, email: str | None = None, lifetime_seconds: int | None = None) -> str:
    """Create a JWT access token for an authenticated user.

    Args:
        user_id:   The stable application owner ID, independent of identity provider.
        user_name: The user's display name.
        user_role: The user's role (admin, researcher, user).

    Returns:
        Encoded JWT string.
    """
    expire = datetime.now(timezone.utc) + (
        timedelta(seconds=lifetime_seconds) if lifetime_seconds is not None
        else timedelta(hours=JWT_EXPIRY_HOURS)
    )
    payload = {
        "sub": user_id,
        "email": email or user_id,
        "name": user_name,
        "role": user_role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT access token.

    Returns:
        A user dict (with ``user_id``) on success, None on failure.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub", "")
        return {
            "user_id": sub,
            "email": payload.get("email", sub),
            "name": payload.get("name", ""),
            "role": payload.get("role", "user"),
        }
    except JWTError as e:
        logger.debug("Token verification failed: %s", e)
        return None
