"""
JWT token creation and validation.

Ported from ast-chatbot/synapsis/auth/tokens.py.

The token payload's ``sub`` claim is the stable identity. It is the app-password
user's email today; it becomes the Cognito ``sub`` when CGIAR Entra ID SSO
federates — the resolver (:func:`synapsis.auth.middleware.resolve_user_id`)
reads ``sub`` in both cases, so the swap is transparent.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from synapsis.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS, logger


def create_access_token(user_id: str, user_name: str, user_role: str) -> str:
    """Create a JWT access token for an authenticated user.

    Args:
        user_id:   The stable identity claim (email now, Cognito ``sub`` later).
        user_name: The user's display name.
        user_role: The user's role (admin, researcher, user).

    Returns:
        Encoded JWT string.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {
        "sub": user_id,
        "email": user_id,
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
