"""
Authentication REST endpoints.

- POST /api/auth/login  — Login with email and password (issued-password path)
- GET  /api/auth/me     — Get current user info from token (or dev-bypass user)

Ported from ast-chatbot/synapsis/auth/routes.py.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from synapsis.auth.users import authenticate_user
from synapsis.auth.tokens import create_access_token
from synapsis.auth.middleware import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate with email and password.

    Returns a JWT token on success. Only allow-listed users can log in.
    """
    user = authenticate_user(body.email, body.password)
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


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's info.

    Requires a valid JWT (or dev-bypass mode). The frontend calls this on load
    to (a) restore a session and (b) detect whether auth is enforced.
    """
    return user
