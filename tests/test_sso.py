"""SSO trust boundaries, browser transactions and legacy identity continuity."""
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from synapsis import config
from synapsis.auth import sso_provider as provider, sso_routes as routes, sso_storage as storage
from synapsis.auth.tokens import verify_token
from synapsis.auth.users import hash_password
from synapsis.database.connection import close_db, get_db


@pytest.fixture
def settings(monkeypatch):
    for name, value in {
        "SSO_ENABLED": True, "SSO_ISSUER": "https://cognito-idp.eu-central-1.amazonaws.com/test_pool",
        "SSO_CLIENT_ID": "expected-client", "SSO_DOMAIN": "https://test.auth.eu-central-1.amazoncognito.com",
        "SSO_ORIGIN": "https://ia.test", "SSO_ALLOWED_DOMAINS": ("cgiar.org",),
    }.items():
        monkeypatch.setattr(config, name, value)
    routes._attempts.clear()


@pytest.fixture
def signer(settings, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(provider, "jwks_client", lambda issuer: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))

    def sign(**overrides):
        claims = {"iss": config.SSO_ISSUER, "aud": config.SSO_CLIENT_ID, "sub": "subject-1",
                  "iat": int(time.time()), "exp": int(time.time()) + 3600,
                  "token_use": "id", "nonce": "expected-nonce", "email": "person@cgiar.org",
                  "name": "Test Person", "identities": [{"providerName": "AzureAD", "providerType": "OIDC"}]}
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})
    return sign


@pytest_asyncio.fixture
async def client(settings, monkeypatch, tmp_path):
    await close_db()
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "chat.db")
    async with get_db() as db:
        await db.execute("CREATE TABLE users (email TEXT PRIMARY KEY, name TEXT, role TEXT, password_hash TEXT, created_at REAL)")
        await db.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, user_id TEXT)")
        await db.commit()
    await storage.init_sso_tables()
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://ia.test",
                           headers={"Origin": "https://ia.test"}) as http:
        yield http
    await close_db()


def test_valid_cognito_id_token(signer):
    claims = provider.decode_id_token(signer(), "expected-nonce")
    assert claims["sub"] == "subject-1"


@pytest.mark.parametrize("change", [
    {"iss": "https://other-pool"}, {"aud": "other-client"}, {"token_use": "access"},
    {"exp": int(time.time()) - 100}, {"nonce": "wrong"}, {"email": "other@example.org"},
    {"identities": []}, {"identities": [{"providerName": "Google", "providerType": "OIDC"}]},
])
def test_invalid_identity_rejected(signer, change):
    with pytest.raises((ValueError, jwt.PyJWTError)):
        provider.decode_id_token(signer(**change), "expected-nonce")


def test_hmac_algorithm_rejected_before_key_lookup(settings):
    forged = jwt.encode({"sub": "admin"}, "not-a-real-secret", algorithm="HS256", headers={"kid": "x"})
    with pytest.raises(ValueError):
        provider.decode_id_token(forged)


@pytest.mark.asyncio
async def test_start_uses_pkce_nonce_exact_callback_and_secure_cookie(client):
    response = await client.get("/api/auth/sso/start")
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert query["redirect_uri"] == ["https://ia.test/auth/callback"]
    assert query["identity_provider"] == ["AzureAD"]
    assert query["state"] and query["nonce"]
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_bad_callback_never_exchanges_code(client, monkeypatch):
    async def forbidden(*args):
        pytest.fail("Must not exchange a code without matching state and cookie")
    monkeypatch.setattr(provider, "exchange_code", forbidden)
    response = await client.get("/auth/callback?code=attacker&state=wrong")
    assert "sso_error" in response.headers["location"]
    started = await client.get("/api/auth/sso/start")
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = await client.get("/auth/callback", params={"code": "attacker", "state": state + "x"})
    assert "sso_error" in response.headers["location"]


async def establish(client, signer, monkeypatch, **claims):
    started = await client.get("/api/auth/sso/start")
    query = parse_qs(urlparse(started.headers["location"]).query)
    async def exchange(code, verifier):
        assert code == "test-code" and len(verifier) == 43
        return {"id_token": signer(nonce=query["nonce"][0], **claims), "refresh_token": "test-refresh"}
    monkeypatch.setattr(provider, "exchange_code", exchange)
    response = await client.get("/auth/callback", params={"code": "test-code", "state": query["state"][0]})
    assert response.headers["location"] == "https://ia.test/?sso=complete"
    assert "test-refresh" not in response.text
    return query


@pytest.mark.asyncio
async def test_callback_replay_and_session_storage(client, signer, monkeypatch):
    query = await establish(client, signer, monkeypatch)
    response = await client.get("/auth/callback", params={"code": "test-code", "state": query["state"][0]})
    assert "sso_error" in response.headers["location"]
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM sso_sessions")).fetchall()
    assert all(b"test-refresh" not in r["payload"] for r in rows)
    assert all(client.cookies.get(routes.SESSION_COOKIE) != r["key_hash"] for r in rows)


@pytest.mark.asyncio
async def test_matching_legacy_email_never_inherits_role_or_old_chats(client, signer, monkeypatch):
    async with get_db() as db:
        await db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)", (
            "person@cgiar.org", "Existing Name", "admin", hash_password("existing-app-password"), time.time()))
        await db.execute("INSERT INTO sessions VALUES ('old-chat', 'person@cgiar.org')")
        await db.commit()
    await establish(client, signer, monkeypatch)
    response = await client.post("/api/auth/sso/session")
    assert response.status_code == 200
    user = verify_token(response.json()["token"])
    assert user["user_id"].startswith("sso:") and user["role"] == "researcher"
    async with get_db() as db:
        old_owner = (await (await db.execute("SELECT user_id FROM sessions WHERE session_id='old-chat'")).fetchone())[0]
        assert old_owner == "person@cgiar.org" and old_owner != user["user_id"]
    assert (await client.post("/api/auth/sso/session")).json()["user"]["user_id"] == user["user_id"]
    assert (await client.post("/api/auth/sso/link", json={"password": "existing-app-password"})).status_code == 404


@pytest.mark.asyncio
async def test_new_users_have_distinct_stable_ids_and_no_admin_claim_trust(client, signer, monkeypatch):
    await establish(client, signer, monkeypatch, role="admin")
    first = (await client.post("/api/auth/sso/session")).json()["user"]
    assert first["user_id"].startswith("sso:") and first["role"] == "researcher"
    await establish(client, signer, monkeypatch, email="second@cgiar.org", sub="subject-2")
    second = (await client.post("/api/auth/sso/session")).json()["user"]
    assert second["user_id"] != first["user_id"]
    await establish(client, signer, monkeypatch, email="renamed@cgiar.org")
    renamed = (await client.post("/api/auth/sso/session")).json()["user"]
    assert renamed["user_id"] == first["user_id"]


@pytest.mark.asyncio
async def test_cross_origin_session_link_logout_rejected(client, signer, monkeypatch):
    await establish(client, signer, monkeypatch)
    for path in ("session", "logout"):
        response = await client.post("/api/auth/sso/" + path, headers={"Origin": "https://evil.example"}, json={"password": "x"})
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_refresh_revalidates_subject_and_logout_invalidates_session(client, signer, monkeypatch):
    await establish(client, signer, monkeypatch)
    key = client.cookies.get(routes.SESSION_COOKIE)
    stored = await storage.get_session(key, "login")
    stored["exp"] = time.time() - 1
    await storage.update_session(key, stored)
    async def refresh(token):
        assert token == "test-refresh"
        return {"id_token": signer()}
    monkeypatch.setattr(provider, "refresh_tokens", refresh)
    assert (await client.post("/api/auth/sso/session")).status_code == 200
    stored = await storage.get_session(key, "login")
    stored["exp"] = time.time() - 1
    await storage.update_session(key, stored)
    async def switched(token):
        return {"id_token": signer(sub="other-person")}
    monkeypatch.setattr(provider, "refresh_tokens", switched)
    assert (await client.post("/api/auth/sso/session")).status_code == 401
    assert await storage.get_session(key, "login") is None
    # Local logout still completes if upstream revocation is unavailable.
    await establish(client, signer, monkeypatch)
    async def unavailable(*args, **kwargs):
        raise RuntimeError("simulated provider outage")
    monkeypatch.setattr(routes.httpx.AsyncClient, "post", unavailable)
    # Call ASGI transport directly because the patched method also affects the test client.
    request = client.build_request("POST", "/api/auth/sso/logout")
    response = await client.send(request)
    assert response.status_code == 200
    assert "logout_uri=https%3A%2F%2Fia.test" in response.json()["logout_url"]
    assert routes.SESSION_COOKIE not in client.cookies


@pytest.mark.asyncio
async def test_disabled_sso_is_closed(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_ENABLED", False)
    assert (await client.get("/api/auth/sso/start")).status_code == 404
    assert (await client.get("/api/auth/sso/config")).json() == {"enabled": False}


@pytest.mark.asyncio
async def test_sso_only_rejects_password_login_and_preexisting_password_tokens(client, monkeypatch):
    from synapsis.auth.routes import router as password_router
    from synapsis.auth.tokens import create_access_token
    monkeypatch.setattr(config, "PASSWORD_LOGIN_ENABLED", False)
    token = create_access_token("old@cgiar.org", "Old Admin", "admin")
    assert verify_token(token) is None
    app = FastAPI()
    app.include_router(password_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://ia.test") as http:
        assert (await http.post("/api/auth/login", json={"email": "old@cgiar.org", "password": "anything"})).status_code == 404
        assert (await http.post("/api/auth/signup", json={"name": "Old", "email": "old@cgiar.org", "password": "anything-long"})).status_code == 404
