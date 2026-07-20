"""
Authentication middleware for FastAPI.

Provides dependencies that extract and validate JWT tokens from the
Authorization header. Routes that need auth use ``get_current_user``; routes
that scope data per-user read the identity via ``resolve_user_id``.

In dev-bypass mode (IA_AUTH_DISABLED=true — the default on local macOS) auth is
skipped and a dummy dev user is returned so local development stays frictionless.
The deployed dev URL sets IA_AUTH_DISABLED=false, so login is enforced there.

Ported from ast-chatbot/synapsis/auth/middleware.py and extended with the
identity-abstraction resolver.

────────────────────────────────────────────────────────────────────────────
HONEST SCOPING LIMITATION (read before assuming this is a security boundary):
This middleware — and the per-user `user_id` filtering it feeds — provides
UI/API-level chat isolation only. It does NOT sandbox the agent's *execution*:
the Claude Agent SDK still runs code (Bash, file I/O, tools) in a single shared
workspace/VM common to all users. A user's PROMPTS and CHAT LIST are private;
the underlying execution environment is not partitioned per user. This is the
deliberate "lighter-weight illusion of separation" the team agreed to on the
July 7, 2026 call, and it is disclosed honestly to Marc rather than shipped as a
false sense of security. True per-user execution-sandbox isolation is a costed
future phase. Full write-up: docs/SECURITY-SCOPING-NOTE.md.
────────────────────────────────────────────────────────────────────────────
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from synapsis.auth.tokens import verify_token
from synapsis.config import AUTH_DISABLED, LEGACY_USER_ID

_bearer_scheme = HTTPBearer(auto_error=False)

_DEV_USER = {
    "user_id": LEGACY_USER_ID,
    "email": "dev@localhost",
    "name": "Development User",
    "role": "admin",
}


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency returning the current authenticated user.

    Extracts the JWT from ``Authorization: Bearer <token>``, validates it, and
    returns the user payload (including ``user_id``).

    In dev-bypass mode, returns a dummy user.

    Raises:
        HTTPException 401: if no token is provided or the token is invalid.
    """
    if AUTH_DISABLED:
        return dict(_DEV_USER)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising 401.

    Useful for endpoints that work for both authenticated and anonymous users.
    """
    if AUTH_DISABLED:
        return dict(_DEV_USER)

    if credentials is None:
        return None

    return verify_token(credentials.credentials)


def resolve_user_id(user: Optional[dict]) -> str:
    """Resolve a user payload to the single stable identity claim: ``user_id``.

    This is the identity abstraction the rest of the app keys on. It reads the
    JWT ``sub`` today (the app-password email) and will read the Cognito ``sub``
    once Entra ID SSO federates — with no change to any caller. Anonymous /
    pre-auth requests resolve to the legacy sentinel so their sessions are not
    silently attributed to a real user.
    """
    if user and user.get("user_id"):
        return str(user["user_id"])
    return LEGACY_USER_ID


def resolve_role(user: Optional[dict]) -> str:
    """Resolve a user payload to its verified ``role`` claim.

    Reads the JWT ``role`` claim (never client input -- ``user`` here is
    always the dict already produced by :func:`get_current_user` /
    :func:`verify_token`, i.e. post-signature-verification). Defaults to
    ``"user"`` for anonymous/missing-role payloads so an unrecognized shape
    never silently grants admin-only visibility.

    Used together with :func:`synapsis.auth.scoping.allowed_user_ids` to grant
    admins visibility into sentinel-owned (pre-auth "legacy") sessions.
    """
    if user and user.get("role"):
        return str(user["role"])
    return "user"
