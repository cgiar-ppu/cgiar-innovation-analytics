"""
JWT token creation and validation.

Ported from ast-chatbot/synapsis/auth/tokens.py.

The token payload's ``sub`` is the stable application identity. SSO users get a fresh
opaque application ID; historical password accounts are not linked. Cognito subjects are never substituted for owner keys.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from synapsis import config

from synapsis.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS, logger


def create_access_token(user_id: str, user_name: str, user_role: str,
                        *, email: str | None = None, lifetime_seconds: int | None = None,
                        auth_source: str = "password", credential_version: int | None = None) -> str:
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
        "auth_source": auth_source,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if credential_version is not None:
        payload["credential_version"] = credential_version
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT access token.

    Returns:
        A user dict (with ``user_id``) on success, None on failure.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        source = payload.get("auth_source", "password")
        if source == "sso" and not config.SSO_ENABLED:
            return None
        if source == "invited":
            from synapsis.auth.invited_storage import credential_is_current
            if not config.INVITED_LOGIN_ENABLED or not credential_is_current(
                payload.get("sub", ""), payload.get("credential_version", -1)
            ):
                return None
        elif source != "sso" and not config.PASSWORD_LOGIN_ENABLED:
            return None
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
