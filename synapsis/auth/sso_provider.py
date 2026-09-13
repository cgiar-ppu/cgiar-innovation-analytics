"""Cognito code/PKCE exchange and strict ID-token verification.

OAuth credentials stay on the server. Only this configured pool, public client
and AzureAD provider can establish an SSO session; app roles come from our DB.
"""
import asyncio
import hmac
import json
from functools import lru_cache
from urllib.parse import urlparse

import jwt as pyjwt
from authlib.integrations.httpx_client import AsyncOAuth2Client

from synapsis import config


def settings() -> dict:
    return {
        "enabled": config.SSO_ENABLED,
        "issuer": config.SSO_ISSUER,
        "client_id": config.SSO_CLIENT_ID,
        "domain": config.SSO_DOMAIN,
        "origin": config.SSO_ORIGIN,
    }


def validate_settings() -> None:
    s = settings()
    if not s["enabled"]:
        return
    for key in ("issuer", "domain", "origin"):
        parsed = urlparse(s[key])
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError(f"SSO {key} must be an exact HTTPS URL")
    if not s["client_id"] or urlparse(s["origin"]).path:
        raise ValueError("SSO requires a client ID and an origin without a path")


def oauth_client(**kwargs):
    s = settings()
    return AsyncOAuth2Client(
        client_id=s["client_id"], token_endpoint_auth_method="none",
        redirect_uri=s["origin"] + "/auth/callback", scope="openid email profile",
        code_challenge_method="S256", timeout=15.0, **kwargs,
    )


async def authorization_url(state: str, nonce: str, verifier: str) -> str:
    async with oauth_client() as client:
        url, _ = client.create_authorization_url(
            settings()["domain"] + "/oauth2/authorize", state=state,
            nonce=nonce, code_verifier=verifier, identity_provider="AzureAD",
        )
    return url


async def exchange_code(code: str, verifier: str) -> dict:
    async with oauth_client() as client:
        return dict(await client.fetch_token(
            settings()["domain"] + "/oauth2/token", code=code,
            code_verifier=verifier, grant_type="authorization_code",
        ))


async def refresh_tokens(refresh_token: str) -> dict:
    async with oauth_client() as client:
        return dict(await client.refresh_token(
            settings()["domain"] + "/oauth2/token", refresh_token=refresh_token,
        ))


@lru_cache(maxsize=4)
def jwks_client(issuer: str):
    # PyJWKClient refetches on an unknown key ID to handle signing-key rotation.
    return pyjwt.PyJWKClient(issuer + "/.well-known/jwks.json", timeout=10, lifespan=300)


def decode_id_token(token: str, nonce: str | None = None) -> dict:
    s = settings()
    header = pyjwt.get_unverified_header(token)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise ValueError("Invalid ID-token signing algorithm")
    key = jwks_client(s["issuer"]).get_signing_key_from_jwt(token).key
    claims = pyjwt.decode(
        token, key, algorithms=["RS256"], issuer=s["issuer"],
        audience=s["client_id"], leeway=15,
        options={"require": ["iss", "sub", "aud", "iat", "exp", "token_use"]},
    )
    if claims["token_use"] != "id" or not claims["sub"]:
        raise ValueError("Expected a Cognito ID token")
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("Invalid OIDC nonce")
    identities = claims.get("identities", [])
    if isinstance(identities, str):
        identities = json.loads(identities)
    if not isinstance(identities, list) or not any(
        isinstance(i, dict) and i.get("providerName") == "AzureAD"
        and i.get("providerType") == "OIDC" for i in identities
    ):
        raise ValueError("Expected the configured Microsoft identity provider")
    email = str(claims.get("email", "")).strip().lower()
    if email.count("@") != 1 or email.rsplit("@", 1)[-1] not in config.SSO_ALLOWED_DOMAINS:
        raise ValueError("A permitted CGIAR work email is required")
    claims["email"] = email
    return claims


async def verify_id_token(token: str, nonce: str | None = None) -> dict:
    return await asyncio.to_thread(decode_id_token, token, nonce)
