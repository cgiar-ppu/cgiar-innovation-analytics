"""Browser-bound SSO: opaque HttpOnly cookies, encrypted server refresh tokens.

The SPA receives short-lived app tokens with stable CGIAR owner IDs. Raw
Cognito tokens and refresh credentials never enter JavaScript or redirect URLs.
"""
import hmac
import secrets
import time
from collections import defaultdict
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from synapsis import config
from synapsis.auth import sso_provider as provider, sso_storage as storage
from synapsis.auth.tokens import create_access_token

router = APIRouter(tags=["sso"])
SESSION_COOKIE = "__Host-ia-sso"
STATE_COOKIE = "__Host-ia-oidc"
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_attempts: dict[tuple, list] = defaultdict(list)


def require_enabled():
    if not config.SSO_ENABLED:
        raise HTTPException(404, "SSO is not enabled")


def require_origin(request: Request):
    if request.headers.get("origin") != config.SSO_ORIGIN:
        raise HTTPException(403, "Invalid request origin")


def rate_limit(request: Request, kind: str, maximum: int):
    now = time.monotonic()
    for key in list(_attempts):
        if not _attempts[key] or _attempts[key][-1] < now - 60:
            del _attempts[key]
    key = (kind, request.client.host if request.client else "unknown")
    recent = _attempts[key] = [t for t in _attempts[key] if t > now - 60]
    if len(recent) >= maximum:
        raise HTTPException(429, "Too many attempts. Please try again in a minute.")
    recent.append(now)


def set_cookie(response, name: str, value: str, lifetime: int):
    response.set_cookie(name, value, max_age=lifetime, secure=True,
                        httponly=True, samesite="lax", path="/")


def clear_cookie(response, name: str):
    response.delete_cookie(name, secure=True, httponly=True, samesite="lax", path="/")


def failed_login():
    response = RedirectResponse(config.SSO_ORIGIN + "/?sso_error=login_failed", status_code=303, headers=NO_STORE)
    clear_cookie(response, STATE_COOKIE)
    return response


@router.get("/api/auth/sso/config")
async def sso_config():
    return JSONResponse({"enabled": config.SSO_ENABLED}, headers=NO_STORE)


@router.get("/api/auth/sso/start")
async def start(request: Request):
    require_enabled()
    rate_limit(request, "start", 20)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    # 43-character random verifier satisfies PKCE length and entropy requirements.
    key = await storage.put_session("transaction", {"state": state, "nonce": nonce, "verifier": verifier}, 600)
    url = await provider.authorization_url(state, nonce, verifier)
    response = RedirectResponse(url, status_code=302, headers=NO_STORE)
    set_cookie(response, STATE_COOKIE, key, 600)
    return response


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request):
    require_enabled()
    try:
        transaction = await storage.get_session(request.cookies.get(STATE_COOKIE, ""), "transaction", consume=True)
        incoming = request.query_params.get("state", "")
        if not transaction or not hmac.compare_digest(transaction["state"], incoming):
            return failed_login()
        code = request.query_params.get("code")
        if request.query_params.get("error") or not code or len(code) > 4096:
            return failed_login()
        tokens = await provider.exchange_code(code, transaction["verifier"])
        claims = await provider.verify_id_token(tokens["id_token"], transaction["nonce"])
        if not tokens.get("refresh_token"):
            return failed_login()
        # Replace any previous browser session only after successful authentication.
        await storage.delete_session(request.cookies.get(SESSION_COOKIE, ""))
        key = await storage.put_session("login", {
            "tokens": tokens, "iss": claims["iss"], "sub": claims["sub"], "exp": claims["exp"],
        }, 86400)
    except Exception as exc:
        # Provider exceptions can contain authorization codes/tokens. Log type only.
        config.logger.warning("SSO callback failed (%s)", type(exc).__name__)
        return failed_login()
    response = RedirectResponse(config.SSO_ORIGIN + "/?sso=complete", status_code=303, headers=NO_STORE)
    clear_cookie(response, STATE_COOKIE)
    set_cookie(response, SESSION_COOKIE, key, 86400)
    return response


async def session_claims(request: Request):
    key = request.cookies.get(SESSION_COOKIE, "")
    try:
        session = await storage.get_session(key, "login")
        if not session:
            raise ValueError("No SSO session")
        tokens = session["tokens"]
        if session["exp"] < time.time() + 90:
            refreshed = await provider.refresh_tokens(tokens["refresh_token"])
            # A refresh response must contain a fresh ID token, never reuse the old one.
            claims = await provider.verify_id_token(refreshed["id_token"])
            tokens = {**tokens, **refreshed}
        else:
            claims = await provider.verify_id_token(tokens["id_token"])
        if claims["iss"] != session["iss"] or claims["sub"] != session["sub"]:
            raise ValueError("SSO refresh changed identity")
        session.update(tokens=tokens, exp=claims["exp"])
        await storage.update_session(key, session)
        return claims
    except Exception as exc:
        config.logger.info("SSO session unavailable (%s)", type(exc).__name__)
        await storage.delete_session(key)
        raise HTTPException(401, "Your CGIAR session has expired. Sign in again.") from None


def app_session(user: dict, claims: dict):
    lifetime = max(1, min(300, int(claims["exp"] - time.time())))
    token = create_access_token(user["user_id"], user["name"], user["role"],
                                email=user["email"], lifetime_seconds=lifetime, auth_source="sso")
    return JSONResponse({"token": token, "user": user, "expires_in": lifetime}, headers=NO_STORE)


@router.post("/api/auth/sso/session")
async def session(request: Request):
    require_enabled()
    require_origin(request)
    claims = await session_claims(request)
    user = await storage.resolve_identity(claims)
    return app_session(user, claims)


@router.post("/api/auth/sso/logout")
async def logout(request: Request):
    require_enabled()
    require_origin(request)
    key = request.cookies.get(SESSION_COOKIE, "")
    try:
        stored = await storage.get_session(key, "login")
        if stored:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(config.SSO_DOMAIN + "/oauth2/revoke", data={
                    "client_id": config.SSO_CLIENT_ID, "token": stored["tokens"]["refresh_token"],
                })
                response.raise_for_status()
    except Exception as exc:
        config.logger.warning("SSO upstream revocation failed (%s)", type(exc).__name__)
    finally:
        await storage.delete_session(key)
    response = JSONResponse({"logout_url": config.SSO_DOMAIN + "/logout?" + urlencode({
        "client_id": config.SSO_CLIENT_ID, "logout_uri": config.SSO_ORIGIN,
    })}, headers=NO_STORE)
    clear_cookie(response, SESSION_COOKIE)
    clear_cookie(response, STATE_COOKIE)
    return response
