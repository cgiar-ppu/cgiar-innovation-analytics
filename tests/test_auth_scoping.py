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


# ---------------------------------------------------------------------------
# Admin-legacy-chat exception (2026-07-20): synapsis/auth/scoping.py
# ---------------------------------------------------------------------------

def test_allowed_user_ids_admin_widens_to_legacy():
    from synapsis.auth.scoping import allowed_user_ids
    from synapsis.config import LEGACY_USER_ID

    assert allowed_user_ids("jose@synapsis-analytics.com", "admin") == [
        "jose@synapsis-analytics.com", LEGACY_USER_ID,
    ]
    # Admin identity that IS the sentinel (e.g. dev-bypass) -> no duplicate.
    assert allowed_user_ids(LEGACY_USER_ID, "admin") == [LEGACY_USER_ID]


def test_allowed_user_ids_non_admin_own_only():
    from synapsis.auth.scoping import allowed_user_ids

    assert allowed_user_ids("ppt.tester@cgiar.org", "researcher") == ["ppt.tester@cgiar.org"]
    assert allowed_user_ids("ppt.tester@cgiar.org", None) == ["ppt.tester@cgiar.org"]
    assert allowed_user_ids("ppt.tester@cgiar.org", "user") == ["ppt.tester@cgiar.org"]


def test_is_visible_to_admin_legacy_exception():
    from synapsis.auth.scoping import is_visible_to
    from synapsis.config import LEGACY_USER_ID

    assert is_visible_to(LEGACY_USER_ID, "jose@synapsis-analytics.com", "admin") is True
    assert is_visible_to(LEGACY_USER_ID, "ppt.tester@cgiar.org", "researcher") is False
    assert is_visible_to("bob@cgiar.org", "alice@cgiar.org", "admin") is False
    assert is_visible_to("alice@cgiar.org", "alice@cgiar.org", "researcher") is True
    # Falsy owner (pre-migration edge case) -- visible regardless of role.
    assert is_visible_to(None, "alice@cgiar.org", "researcher") is True
    assert is_visible_to("", "alice@cgiar.org", "researcher") is True


# ---------------------------------------------------------------------------
# Admin-legacy-chat exception -- REST layer (list/history/export/delete)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_client_legacy(initialized_db):
    """Async client with auth ENFORCED: an admin, a researcher, and one
    sentinel-owned ("legacy" / pre-auth) session."""
    from synapsis.database import create_session, save_message
    from synapsis.config import LEGACY_USER_ID

    await create_session("s-admin", title="Admin's own chat", user_id="admin@cgiar.org")
    await save_message("s-admin", "user", {"content": "admin question"})
    await create_session("s-researcher", title="Researcher's own chat", user_id="researcher@cgiar.org")
    await save_message("s-researcher", "user", {"content": "researcher question"})
    await create_session("s-legacy", title="Old pre-login chat", user_id=LEGACY_USER_ID)
    await save_message("s-legacy", "user", {"content": "legacy question"})

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
async def test_admin_sees_own_and_legacy_sessions(auth_client_legacy):
    admin = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}
    resp = await auth_client_legacy.get("/api/sessions", headers=admin)
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    ids = {s["session_id"] for s in sessions}
    assert ids == {"s-admin", "s-legacy"}
    assert "s-researcher" not in ids

    legacy_entry = next(s for s in sessions if s["session_id"] == "s-legacy")
    admin_entry = next(s for s in sessions if s["session_id"] == "s-admin")
    assert legacy_entry["is_legacy"] is True
    assert admin_entry["is_legacy"] is False


@pytest.mark.asyncio
async def test_admin_can_open_and_export_legacy_session(auth_client_legacy):
    admin_headers = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}

    hist = await auth_client_legacy.get("/api/history/s-legacy", headers=admin_headers)
    assert hist.status_code == 200
    assert hist.json()["messages"], "admin should see the legacy session's messages"

    admin_token = _token_for("admin@cgiar.org", role="admin")
    export = await auth_client_legacy.get(f"/api/export/s-legacy?format=md&token={admin_token}")
    assert export.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_rename_pin_and_delete_legacy_session(auth_client_legacy):
    admin = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}

    rename = await auth_client_legacy.patch(
        "/api/sessions/s-legacy", json={"title": "Renamed by admin"}, headers=admin,
    )
    assert rename.status_code == 200

    pin = await auth_client_legacy.post(
        "/api/sessions/s-legacy/pin", json={"pinned": True}, headers=admin,
    )
    assert pin.status_code == 200

    delete = await auth_client_legacy.delete("/api/sessions/s-legacy", headers=admin)
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_researcher_cannot_see_legacy_or_others_sessions(auth_client_legacy):
    researcher = {"Authorization": f"Bearer {_token_for('researcher@cgiar.org', role='researcher')}"}

    resp = await auth_client_legacy.get("/api/sessions", headers=researcher)
    ids = {s["session_id"] for s in resp.json()["sessions"]}
    assert ids == {"s-researcher"}

    legacy_hist = await auth_client_legacy.get("/api/history/s-legacy", headers=researcher)
    assert legacy_hist.status_code == 404

    others_hist = await auth_client_legacy.get("/api/history/s-admin", headers=researcher)
    assert others_hist.status_code == 404

    legacy_delete = await auth_client_legacy.delete("/api/sessions/s-legacy", headers=researcher)
    assert legacy_delete.status_code == 404

    researcher_token = _token_for("researcher@cgiar.org", role="researcher")
    legacy_export = await auth_client_legacy.get(f"/api/export/s-legacy?format=md&token={researcher_token}")
    assert legacy_export.status_code == 404


@pytest.mark.asyncio
async def test_admin_new_session_creation_still_attributed_to_admin(initialized_db):
    """Widening VISIBILITY for admins must not change CREATION attribution:
    a session an admin creates is owned by the admin, never the sentinel."""
    from synapsis.database import create_session, get_session_owner
    from synapsis.auth.context import set_current_user_id
    from synapsis.config import LEGACY_USER_ID

    set_current_user_id("admin@cgiar.org", "admin")
    try:
        await create_session("s-new-by-admin")
        owner = await get_session_owner("s-new-by-admin")
        assert owner == "admin@cgiar.org"
        assert owner != LEGACY_USER_ID
    finally:
        # Reset the contextvar so it doesn't leak into other tests.
        set_current_user_id(LEGACY_USER_ID, "user")


# ---------------------------------------------------------------------------
# Admin-legacy-chat exception -- WebSocket switch_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_switch_session_admin_legacy_ok_researcher_blocked(initialized_db):
    """The switch_session ownership gate in synapsis/websocket.py must let an
    admin resume a sentinel-owned ("legacy") session and must still reject a
    researcher with the existing 404-equivalent error semantics.

    Uses a minimal in-process fake WebSocket (no live server, no real SDK
    subprocess -- the SDK client factory is patched out) so this never talks
    to a live agent or incurs any cost.
    """
    import json as _json
    from types import SimpleNamespace
    from starlette.websockets import WebSocketState

    from synapsis.database import create_session, save_message
    from synapsis.config import LEGACY_USER_ID
    from synapsis.websocket import ws_chat
    from synapsis.session.client_registry import ClientRegistry

    await create_session("s-ws-legacy", title="Legacy WS chat", user_id=LEGACY_USER_ID)
    await save_message("s-ws-legacy", "user", {"content": "hi"})

    class FakeWebSocket:
        def __init__(self, frames):
            self._frames = list(frames)
            self.sent = []
            self.client_state = WebSocketState.CONNECTED
            self.close_code = None
            self.close_reason = None

        async def accept(self):
            pass

        async def receive_text(self):
            if not self._frames:
                from fastapi import WebSocketDisconnect
                raise WebSocketDisconnect()
            return self._frames.pop(0)

        async def send_json(self, data):
            self.sent.append(data)

        async def close(self, code=1000, reason=""):
            self.client_state = WebSocketState.DISCONNECTED
            self.close_code = code
            self.close_reason = reason

    async def fake_create_and_connect_client(self, resume_session_id=None, model=None):
        # Stand-in for a connected ClaudeSDKClient -- never spawns a real
        # subprocess and never talks to a live agent.
        return SimpleNamespace()

    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.websocket.AUTH_DISABLED", False),
        patch.object(ClientRegistry, "_create_and_connect_client", fake_create_and_connect_client),
    ):
        admin_token = _token_for("admin@cgiar.org", role="admin")
        ws_admin = FakeWebSocket([
            _json.dumps({"type": "switch_session", "session_id": "s-ws-legacy"}),
        ])
        await ws_chat(ws_admin, token=admin_token)

        assert not any(f.get("type") == "error" for f in ws_admin.sent), ws_admin.sent
        assert any(
            f.get("type") == "session" and f.get("session_id") == "s-ws-legacy"
            for f in ws_admin.sent
        ), ws_admin.sent

        researcher_token = _token_for("researcher@cgiar.org", role="researcher")
        ws_researcher = FakeWebSocket([
            _json.dumps({"type": "switch_session", "session_id": "s-ws-legacy"}),
        ])
        await ws_chat(ws_researcher, token=researcher_token)

        assert any(
            f.get("type") == "error" and "not found" in f.get("message", "").lower()
            for f in ws_researcher.sent
        ), ws_researcher.sent
        assert not any(
            f.get("type") == "session" and f.get("session_id") == "s-ws-legacy"
            for f in ws_researcher.sent
        ), ws_researcher.sent
