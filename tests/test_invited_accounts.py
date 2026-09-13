"""Invitation possession, authorization, expiry, reset and revocation boundaries."""
import time
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from synapsis import config
from synapsis.auth import invited_storage as store, middleware, sso_routes
from synapsis.auth.invited_routes import router
from synapsis.auth.routes import router as auth_router
from synapsis.auth.sso_storage import init_sso_tables, resolve_identity
from synapsis.auth.tokens import create_access_token, verify_token
from synapsis.auth.users import hash_password
from synapsis.database.connection import close_db, get_db


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    await close_db()
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "chat.db")
    monkeypatch.setattr(config, "INVITED_LOGIN_ENABLED", True)
    monkeypatch.setattr(config, "PASSWORD_LOGIN_ENABLED", False)
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    monkeypatch.setattr(config, "SSO_ORIGIN", "https://ia.test")
    monkeypatch.setattr(config, "SSO_ALLOWED_DOMAINS", ("cgiar.org",))
    monkeypatch.setattr(middleware, "AUTH_DISABLED", False)
    sso_routes._attempts.clear()
    await store.init_invited_tables()
    await init_sso_tables()
    app = FastAPI()
    app.include_router(router)
    app.include_router(auth_router)
    admin = create_access_token("sso:administrator", "Admin", "admin", auth_source="sso")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://ia.test",
                           headers={"Origin": "https://ia.test", "Authorization": "Bearer " + admin}) as http:
        yield http
    await close_db()


async def invite(client, email="researcher@example.org"):
    response = await client.post("/api/auth/invitations", json={"email": email, "name": "External Researcher"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    url = urlparse(response.json()["invitation_url"])
    assert not url.query
    return parse_qs(url.fragment)["invite"][0]


@pytest.mark.asyncio
async def test_invite_activation_login_and_one_use(client):
    token = await invite(client)
    denied = await client.post("/api/auth/login", json={"email": "researcher@example.org", "password": "long-test-password"})
    assert denied.status_code == 401
    preview = await client.post("/api/auth/invitation/inspect", json={"token": token})
    assert preview.json()["email"] == "researcher@example.org"
    response = await client.post("/api/auth/invitation/accept", json={"token": token, "password": "long-test-password"})
    assert response.status_code == 200
    user = verify_token(response.json()["token"])
    assert user["user_id"].startswith("invited:") and user["role"] == "researcher"
    assert (await client.post("/api/auth/invitation/accept", json={"token": token, "password": "long-test-password"})).status_code == 410
    signed_in = await client.post("/api/auth/login", json={"email": "RESEARCHER@example.org", "password": "long-test-password"})
    assert signed_in.status_code == 200 and signed_in.json()["user"]["user_id"] == user["user_id"]
    listing = await client.get("/api/auth/invitations")
    assert "password_hash" not in listing.text and token not in listing.text


@pytest.mark.asyncio
async def test_only_admin_can_invite_and_origin_is_checked(client):
    researcher = create_access_token("sso:researcher", "Researcher", "researcher", auth_source="sso")
    body = {"email": "outsider@example.org", "name": "Outsider"}
    assert (await client.post("/api/auth/invitations", json=body, headers={"Authorization": "Bearer " + researcher})).status_code == 403
    assert (await client.post("/api/auth/invitations", json=body, headers={"Authorization": ""})).status_code == 401
    assert (await client.post("/api/auth/invitations", json=body, headers={"Origin": "https://evil.example"})).status_code == 403
    assert (await client.post("/api/auth/invitations", json={"email": "staff@cgiar.org", "name": "Staff"})).status_code == 422


@pytest.mark.asyncio
async def test_expired_or_replaced_invites_cannot_activate(client):
    old = await invite(client)
    replacement = await invite(client)
    assert (await client.post("/api/auth/invitation/inspect", json={"token": old})).status_code == 410
    async with get_db() as db:
        await db.execute("UPDATE account_invitations SET expires_at=?", (time.time() - 1,))
        await db.commit()
    assert (await client.post("/api/auth/invitation/accept", json={"token": replacement, "password": "long-test-password"})).status_code == 410


@pytest.mark.asyncio
async def test_reset_and_revocation_invalidate_issued_tokens(client):
    token = await invite(client)
    response = await client.post("/api/auth/invitation/accept", json={"token": token, "password": "long-test-password"})
    original = response.json()["token"]
    owner = response.json()["user"]["user_id"]
    reset = await invite(client)
    response = await client.post("/api/auth/invitation/accept", json={"token": reset, "password": "new-long-test-password"})
    refreshed = response.json()["token"]
    assert response.json()["user"]["user_id"] == owner
    assert verify_token(original) is None and verify_token(refreshed)
    assert (await client.post("/api/auth/login", json={"email": "researcher@example.org", "password": "long-test-password"})).status_code == 401
    await client.post("/api/auth/invitations/revoke", json={"email": "researcher@example.org", "name": "External"})
    assert verify_token(refreshed) is None
    assert (await client.post("/api/auth/login", json={"email": "researcher@example.org", "password": "new-long-test-password"})).status_code == 401


@pytest.mark.asyncio
async def test_legacy_users_do_not_become_invited_users(client):
    async with get_db() as db:
        await db.execute("CREATE TABLE users (email TEXT PRIMARY KEY,name TEXT,role TEXT,password_hash TEXT,created_at REAL)")
        await db.execute("INSERT INTO users VALUES (?,?,?,?,?)", ("old@example.org", "Old Admin", "admin", hash_password("long-test-password"), time.time()))
        await db.commit()
    old_token = create_access_token("old@example.org", "Old Admin", "admin")
    assert verify_token(old_token) is None
    assert (await client.post("/api/auth/login", json={"email": "old@example.org", "password": "long-test-password"})).status_code == 401
    token = await invite(client, "old@example.org")
    response = await client.post("/api/auth/invitation/accept", json={"token": token, "password": "new-long-test-password"})
    assert response.json()["user"]["role"] == "researcher"
    assert response.json()["user"]["user_id"].startswith("invited:")


@pytest.mark.asyncio
async def test_disabled_invited_path_fails_closed(client, monkeypatch):
    monkeypatch.setattr(config, "INVITED_LOGIN_ENABLED", False)
    assert (await client.get("/api/auth/invitations")).status_code == 404
    assert (await client.post("/api/auth/login", json={"email": "old@example.org", "password": "anything"})).status_code == 404


@pytest.mark.asyncio
async def test_admin_is_assigned_by_configured_subject_not_email_or_claim(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_ADMIN_SUBJECTS", ("owner-subject",))
    claims = {"iss": "https://trusted-pool", "sub": "owner-subject", "email": "owner@cgiar.org", "name": "Owner"}
    assert (await resolve_identity(claims))["role"] == "admin"
    assert (await resolve_identity({**claims, "sub": "other-subject", "role": "admin"}))["role"] == "researcher"
    monkeypatch.setattr(config, "SSO_ADMIN_SUBJECTS", ())
    assert (await resolve_identity(claims))["role"] == "researcher"
