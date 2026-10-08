"""Administrator-issued links and invited-user activation; no public signup."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

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


COHORT_PATTERN = re.compile(r"[\w .,:;()/&+'#-]{1,60}")


def valid_cohort(value):
    """Cohort label for a test round, e.g. "WB TTLs Oct-2026". '' = none."""
    if value is None:
        return None
    value = " ".join(str(value).split())
    if value and not COHORT_PATTERN.fullmatch(value):
        raise ValueError("Cohort labels use up to 60 letters, digits, spaces and simple punctuation")
    return value


def valid_external_email(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Enter a valid email address")
    if value.rsplit("@", 1)[-1] in config.SSO_ALLOWED_DOMAINS:
        raise ValueError("CGIAR staff should use CGIAR SSO")
    return value


def valid_name(value):
    if not value.strip():
        raise ValueError("A name is required")
    return value.strip()


class Invitee(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        return valid_name(value)

    @field_validator("email")
    @classmethod
    def external_email(cls, value):
        return valid_external_email(value)


class InvitationRequest(Invitee):
    # Optional test-round fields (2026-09-26). cohort None = keep the account's
    # current label (reissue), '' = clear it. Revoke ignores both.
    cohort: str | None = Field(default=None, max_length=80)
    expires_in_days: int = Field(default=store.DEFAULT_EXPIRY_DAYS, ge=1, le=store.MAX_EXPIRY_DAYS)

    @field_validator("cohort")
    @classmethod
    def cohort_label(cls, value):
        return valid_cohort(value)


class BulkInvitationRequest(BaseModel):
    """Several invitations for one named test group. Links go back to the admin only."""
    invitees: list[dict] = Field(min_length=1, max_length=50)
    cohort: str = Field(default="", max_length=80)
    expires_in_days: int = Field(default=store.DEFAULT_EXPIRY_DAYS, ge=1, le=store.MAX_EXPIRY_DAYS)

    @field_validator("cohort")
    @classmethod
    def cohort_label(cls, value):
        return valid_cohort(value)


class CohortRequest(BaseModel):
    email: str = Field(max_length=254)
    cohort: str = Field(default="", max_length=80)

    @field_validator("cohort")
    @classmethod
    def cohort_label(cls, value):
        return valid_cohort(value)


class CohortRevokeRequest(BaseModel):
    cohort: str = Field(min_length=1, max_length=80)

    @field_validator("cohort")
    @classmethod
    def cohort_label(cls, value):
        return valid_cohort(value)


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


def invitation_url(token: str) -> str:
    # Fragment is handled locally and stripped before rendering; no token in HTTP URLs/logs.
    return config.SSO_ORIGIN + "/#invite=" + token


@router.post("/invitations")
async def invite(body: InvitationRequest, request: Request, user=Depends(admin)):
    require_origin(request)
    rate_limit(request, "invite", 20)
    token = await store.create_invitation(body.email, body.name.strip(), user["user_id"],
                                          cohort=body.cohort, expires_days=body.expires_in_days)
    return JSONResponse({"invitation_url": invitation_url(token), "expires_in_days": body.expires_in_days,
                         "cohort": body.cohort}, headers=NO_STORE)


@router.post("/invitations/bulk")
async def invite_many(body: BulkInvitationRequest, request: Request, user=Depends(admin)):
    """One link per invitee, all labelled with the cohort. Nothing is emailed:
    the admin copies each link and shares it privately. Invalid rows are
    reported and skipped; valid rows are created."""
    require_origin(request)
    rate_limit(request, "invite-bulk", 10)
    created, errors, seen = [], [], set()
    for raw in body.invitees:
        label = str(raw.get("email", ""))[:254] if isinstance(raw, dict) else ""
        try:
            invitee = Invitee.model_validate(raw)
        except ValidationError as exc:
            errors.append({"email": label, "error": exc.errors()[0].get("msg", "Invalid entry").removeprefix("Value error, ")})
            continue
        if invitee.email in seen:
            errors.append({"email": invitee.email, "error": "Listed twice"})
            continue
        seen.add(invitee.email)
        token = await store.create_invitation(invitee.email, invitee.name, user["user_id"],
                                              cohort=body.cohort, expires_days=body.expires_in_days)
        created.append({"email": invitee.email, "name": invitee.name, "invitation_url": invitation_url(token)})
    return JSONResponse({"cohort": body.cohort, "expires_in_days": body.expires_in_days,
                         "invitations": created, "errors": errors}, headers=NO_STORE)


@router.post("/invitations/cohort")
async def change_cohort(body: CohortRequest, request: Request, user=Depends(admin)):
    require_origin(request)
    if not await store.set_cohort(body.email.strip().lower(), body.cohort):
        raise HTTPException(404, "No invited account with that email")
    return {"email": body.email.strip().lower(), "cohort": body.cohort}


@router.post("/invitations/revoke-cohort")
async def revoke_cohort(body: CohortRevokeRequest, request: Request, user=Depends(admin)):
    """End a test round: revoke every account in the cohort (links and sign-ins)."""
    require_origin(request)
    return {"cohort": body.cohort, "revoked": await store.revoke_cohort(body.cohort)}


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
