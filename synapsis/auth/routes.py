"""
Authentication REST endpoints.

- POST /api/auth/login  — Login with email and password (issued-password path)
- POST /api/auth/signup — Interim self-signup, no email confirmation (flag-gated)
- GET  /api/auth/me     — Get current user info from token (or dev-bypass user)

Ported from ast-chatbot/synapsis/auth/routes.py.
"""

import re
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from synapsis.auth.users import authenticate_user, get_user_by_email, hash_password
from synapsis.auth.tokens import create_access_token
from synapsis.auth.middleware import get_current_user
from synapsis.config import SELF_SIGNUP_ENABLED, SIGNUP_ALLOWED_DOMAINS, logger

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Signup domain allow-list (IA_SIGNUP_ALLOWED_DOMAINS, default "cgiar.org")
#
# Jose -> Marc Schut, 2026-07-22: signup "is not allowed to avoid anyone just
# using it (without a CG email)". The interim signup endpoint accepted ANY
# address; these helpers make the code match that stated policy.
# ---------------------------------------------------------------------------

def _signup_domain_allowed(email: str) -> bool:
    """Return True if `email`'s domain is on the self-signup allow-list.

    Exact, case-insensitive match on the part after the LAST "@". Subdomains
    do NOT match (``x@mail.cgiar.org`` is rejected under the default) — see
    ``synapsis.config._parse_signup_allowed_domains`` for the rationale. An
    empty allow-list means the restriction is disabled.

    Reads the module-level ``SIGNUP_ALLOWED_DOMAINS`` at call time so tests
    (and future runtime overrides) can patch it, mirroring how
    ``SELF_SIGNUP_ENABLED`` is patched.
    """
    if not SIGNUP_ALLOWED_DOMAINS:
        return True
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in [d.lower() for d in SIGNUP_ALLOWED_DOMAINS]


def _signup_domain_message() -> str:
    """User-facing rejection message naming the allowed domain(s)."""
    domains = ", ".join(f"@{d}" for d in SIGNUP_ALLOWED_DOMAINS)
    return (
        f"Self-signup is restricted to CGIAR email addresses ({domains}). "
        "If you believe you should have access, contact the team."
    )


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate with email and password.

    Returns a JWT token on success. Only known users (baked-in allow-list or
    self-signed-up) can log in.
    """
    user = await authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        user_id=user["user_id"],
        user_name=user["name"],
        user_role=user["role"],
    )

    return {"token": token, "user": user}


# ---------------------------------------------------------------------------
# Interim self-signup (no email confirmation) — gated behind IA_SELF_SIGNUP.
#
# Deliberately minimal per the July-20 brief: this is an interim measure so
# researchers can get access without waiting on a manual allow-list edit and
# redeploy. It is NOT a replacement for the planned CGIAR Entra ID SSO path.
# Defaults OFF in code (SELF_SIGNUP_ENABLED); deploy.yml only flips it on for
# the dev stage's container, so the prod lineage stays closed even if this
# code is later promoted unchanged.
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str
    name: str
    password: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required.")
        return v

    @field_validator("password")
    @classmethod
    def _strong_enough_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


# In-process, best-effort abuse guard: N signups per minute per client IP.
# Interim and minimal by design — resets on restart, not shared across
# containers. A real rate limiter (e.g. ALB/WAF) is out of scope here.
_SIGNUP_RATE_LIMIT = 5
_SIGNUP_RATE_WINDOW_SECONDS = 60.0
_signup_attempts: dict[str, list[float]] = defaultdict(list)


def _signup_rate_limited(client_ip: str) -> bool:
    """Return True if `client_ip` has exceeded the signup rate limit."""
    now = time.time()
    attempts = _signup_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < _SIGNUP_RATE_WINDOW_SECONDS]
    if len(attempts) >= _SIGNUP_RATE_LIMIT:
        return True
    attempts.append(now)
    return False


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request):
    """Interim self-signup: create an account and log in immediately.

    No email confirmation — the account is usable the instant this call
    returns (same payload shape as /login: token + user). Always creates
    role=`researcher`. Gated behind IA_SELF_SIGNUP; returns 404 when the flag
    is off so the endpoint's existence isn't advertised in closed deployments
    (e.g. the current prod lineage).
    """
    if not SELF_SIGNUP_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    client_ip = request.client.host if request.client else "unknown"
    if _signup_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many signup attempts. Try again in a minute.",
        )

    email = body.email.lower().strip()

    # Domain allow-list (IA_SIGNUP_ALLOWED_DOMAINS, default "cgiar.org").
    # Checked BEFORE the uniqueness lookup so a disallowed address never
    # learns whether an account exists.
    if not _signup_domain_allowed(email):
        logger.info(
            "Self-signup rejected (domain not allowed): %s (allow-list=%s)",
            email, SIGNUP_ALLOWED_DOMAINS,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_signup_domain_message(),
        )

    existing = await get_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    from synapsis.database.users import create_user_row

    password_hash = hash_password(body.password)
    try:
        await create_user_row(email, body.name.strip(), password_hash, role="researcher")
    except Exception as e:
        # Defends against a duplicate-email race between the check above and
        # the insert (two concurrent signups for the same email).
        logger.warning("Signup insert failed for %s: %s", email, e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    logger.info("Self-signup: new researcher account created for %s", email)

    user = {"user_id": email, "email": email, "name": body.name.strip(), "role": "researcher"}
    token = create_access_token(user_id=user["user_id"], user_name=user["name"], user_role=user["role"])

    return {"token": token, "user": user}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's info.

    Requires a valid JWT (or dev-bypass mode). The frontend calls this on load
    to (a) restore a session and (b) detect whether auth is enforced.
    """
    return user
