"""Administrator-issued links and invited-user activation; no public signup."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from synapsis import config
from synapsis.auth import invited_storage as store
from synapsis.auth.middleware import get_current_user
from synapsis.auth.sso_routes import NO_STORE, rate_limit, require_origin
from synapsis.auth.tokens import create_access_token

router = APIRouter(prefix="/api/auth", tags=["invitations"])


def require_enabled():
    if not config.INVITED_LOGIN_ENABLED:
        raise HTTPException(404, "Invited accounts are not enabled")


def admin(user: dict = Depends(get_current_user)):
    require_enabled()
    if user.get("role") != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


class InvitationRequest(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("A name is required")
        return value.strip()

    @field_validator("email")
    @classmethod
    def valid_external_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        if value.rsplit("@", 1)[-1] in config.SSO_ALLOWED_DOMAINS:
            raise ValueError("CGIAR staff should use CGIAR SSO")
        return value


class InvitationToken(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class ActivationRequest(InvitationToken):
    password: str = Field(min_length=12, max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode()) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return value


def login_response(user):
    token = create_access_token(user["user_id"], user["name"], "researcher", email=user["email"],
                                auth_source="invited", credential_version=user["credential_version"],
                                lifetime_seconds=8 * 3600)
    return JSONResponse({"token": token, "user": {k:v for k,v in user.items() if k != "credential_version"}}, headers=NO_STORE)


@router.get("/invitations")
async def accounts(user=Depends(admin)):
    return JSONResponse(await store.list_accounts(), headers=NO_STORE)


@router.post("/invitations")
async def invite(body: InvitationRequest, request: Request, user=Depends(admin)):
    require_origin(request)
    rate_limit(request, "invite", 20)
    token = await store.create_invitation(body.email, body.name.strip(), user["user_id"])
    # Fragment is handled locally and stripped before rendering; no token in HTTP URLs/logs.
    return JSONResponse({"invitation_url": config.SSO_ORIGIN + "/#invite=" + token, "expires_in_days": 7}, headers=NO_STORE)


@router.post("/invitations/revoke")
async def revoke(body: InvitationRequest, request: Request, user=Depends(admin)):
    require_origin(request)
    await store.revoke(body.email)
    return {"revoked": True}


@router.post("/invitation/inspect")
async def inspect(body: InvitationToken, request: Request):
    require_enabled()
    require_origin(request)
    rate_limit(request, "inspect-invite", 30)
    invitation = await store.inspect_invitation(body.token)
    if not invitation:
        raise HTTPException(410, "This invitation has expired or was already used. Ask your administrator for a new link.")
    return JSONResponse(invitation, headers=NO_STORE)


@router.post("/invitation/accept")
async def accept(body: ActivationRequest, request: Request):
    require_enabled()
    require_origin(request)
    rate_limit(request, "accept-invite", 10)
    user = await store.accept_invitation(body.token, body.password)
    if not user:
        raise HTTPException(410, "This invitation has expired or was already used.")
    return login_response(user)
