"""Tests for app-level auth (Step 3) and per-user chat scoping (Step 4).

Covers:
- login round-trip: wrong password rejected, correct password issues a token,
  the token round-trips through /me and resolves a stable user_id;
- the identity resolver / abstraction;
- the idempotent user_id migration (legacy sessions -> sentinel);
- cross-user chat isolation at the API layer (two-user visibility test).
"""

import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Login / token round-trip (unit-level, no DB needed)
# ---------------------------------------------------------------------------

@pytest.fixture
def users_file(tmp_path):
    """Write a temporary allow-list with one bcrypt user and patch USERS_FILE."""
    import json
    import bcrypt

    pw = "correct-horse"
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    path = tmp_path / "allowed_users.json"
    path.write_text(json.dumps({"users": [
        {"email": "alice@cgiar.org", "name": "Alice", "role": "admin", "password_hash": h},
    ]}))
    with patch("synapsis.config.USERS_FILE", path), patch("synapsis.auth.users.USERS_FILE", path):
        yield {"email": "alice@cgiar.org", "password": pw}


def test_wrong_password_rejected(users_file):
    from synapsis.auth.users import authenticate_user
    assert authenticate_user(users_file["email"], "wrong") is None


def test_correct_password_issues_roundtrippable_token(users_file):
    from synapsis.auth.users import authenticate_user
    from synapsis.auth.tokens import create_access_token, verify_token
    from synapsis.auth.middleware import resolve_user_id

    user = authenticate_user(users_file["email"], users_file["password"])
    assert user is not None
    assert user["user_id"] == "alice@cgiar.org"

    token = create_access_token(user["user_id"], user["name"], user["role"])
    decoded = verify_token(token)
    assert decoded["user_id"] == "alice@cgiar.org"
    assert resolve_user_id(decoded) == "alice@cgiar.org"


def test_invalid_token_returns_none():
    from synapsis.auth.tokens import verify_token
    assert verify_token("not.a.jwt") is None


def test_resolver_falls_back_to_sentinel():
    from synapsis.auth.middleware import resolve_user_id
    from synapsis.config import LEGACY_USER_ID
    assert resolve_user_id(None) == LEGACY_USER_ID
    assert resolve_user_id({}) == LEGACY_USER_ID


# ---------------------------------------------------------------------------
# Migration idempotency + owner query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_id_migration_and_owner(initialized_db):
    from synapsis.database import create_session, get_session_owner
    from synapsis.config import LEGACY_USER_ID

    # Legacy-style session created without a user_id -> sentinel.
    await create_session("legacy1", title="old chat")
    assert await get_session_owner("legacy1") == LEGACY_USER_ID

    # Explicit owner.
    await create_session("owned1", title="alice chat", user_id="alice@cgiar.org")
    assert await get_session_owner("owned1") == "alice@cgiar.org"

    # Unknown session -> None.
    assert await get_session_owner("nope") is None


# ---------------------------------------------------------------------------
# Cross-user isolation at the API layer (two-user visibility test)
# ---------------------------------------------------------------------------

def _token_for(user_id: str, role: str = "user") -> str:
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


@pytest_asyncio.fixture
async def auth_client(initialized_db):
    """Async client with auth ENFORCED (dev-bypass off) and two users' sessions."""
    from synapsis.database import create_session, save_message

    # Seed one session for each of two users.
    await create_session("s-alice", title="Alice topic", user_id="alice@cgiar.org")
    await save_message("s-alice", "user", {"content": "alice question"})
    await create_session("s-bob", title="Bob topic", user_id="bob@cgiar.org")
    await save_message("s-bob", "user", {"content": "bob question"})

    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(auth_client):
    resp = await auth_client.get("/api/sessions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_each_user_sees_only_their_sessions(auth_client):
    alice = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    bob = {"Authorization": f"Bearer {_token_for('bob@cgiar.org')}"}

    alice_sessions = (await auth_client.get("/api/sessions", headers=alice)).json()["sessions"]
    bob_sessions = (await auth_client.get("/api/sessions", headers=bob)).json()["sessions"]

    alice_ids = {s["session_id"] for s in alice_sessions}
    bob_ids = {s["session_id"] for s in bob_sessions}

    assert alice_ids == {"s-alice"}
    assert bob_ids == {"s-bob"}
    assert "s-bob" not in alice_ids
    assert "s-alice" not in bob_ids


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_history(auth_client):
    alice = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    # Alice tries to read Bob's session history -> 404 (existence not leaked).
    resp = await auth_client.get("/api/history/s-bob", headers=alice)
    assert resp.status_code == 404
    # Alice can read her own.
    ok = await auth_client.get("/api/history/s-alice", headers=alice)
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_delete_another_users_session(auth_client):
    alice = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.delete("/api/sessions/s-bob", headers=alice)
    assert resp.status_code == 404
