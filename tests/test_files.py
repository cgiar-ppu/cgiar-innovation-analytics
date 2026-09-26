"""Tests for the files API auth gap fix (2026-07-20).

Covers:
- GET /api/files: 401 unauthenticated, 200 with a valid Bearer token.
- GET /api/files/{path}: 401 with neither header nor ?token=, 200 with a
  Bearer header, 200 with ?token= (the plain-<a>-link path), and a rejected
  ``../`` path-traversal escape.
- POST /api/upload: 401 unauthenticated, 200 with a valid Bearer token.
- Dev-bypass mode (AUTH_DISABLED=True, the local macOS default): all three
  endpoints work with no token at all, matching every other route.

Per-owner files (2026-09-26, review L4-03/L6-09/L1-05): uploads and agent
outputs live under ``<area>/u/<owner-key>/``; a caller lists/downloads only
their own; legacy shared files are admin-only; SVG is never served inline.
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport


def _token_for(user_id: str, role: str = "user") -> str:
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


def _own_output(ws, user_id, token, name):
    from synapsis.user_files import owner_area
    folder = owner_area("outputs", user_id, ws) / token
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _rel(ws, path):
    return str(path.relative_to(ws))


@pytest.fixture
def workspace(tmp_path):
    """A throwaway workspace dir with one seeded file, patched into files.py."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "outputs").mkdir()
    # Legacy shared file (pre-2026-09-26 flat layout): administrators only.
    (ws / "outputs" / "report.txt").write_text("hello report")
    # Alice's own agent output, in her per-owner area.
    alice = _own_output(ws, "alice@cgiar.org", "tok1", "alice-report.txt")
    alice.write_text("alice report")
    # Bob's own output: never visible to Alice.
    _own_output(ws, "bob@cgiar.org", "tok2", "bob-report.txt").write_text("bob private")
    # A secret sibling directory OUTSIDE the workspace whose name shares a
    # string prefix with it -- proves the traversal check is boundary-exact,
    # not a naive str.startswith.
    sibling = tmp_path / "workspace-secret"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("should never be reachable")
    with patch("synapsis.routes.files.WORKSPACE", ws), patch("synapsis.config.WORKSPACE", ws):
        yield ws


@pytest.fixture
async def auth_client(workspace):
    """Client with auth ENFORCED (dev-bypass off)."""
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.routes.files.AUTH_DISABLED", False),
    ):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
async def bypass_client(workspace):
    """Client with dev-bypass auth (the local macOS default)."""
    with (
        patch("synapsis.config.AUTH_DISABLED", True),
        patch("synapsis.auth.middleware.AUTH_DISABLED", True),
        patch("synapsis.routes.files.AUTH_DISABLED", True),
    ):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# GET /api/files (list)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_files_401_unauthenticated(auth_client):
    resp = await auth_client.get("/api/files")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_files_200_with_token(auth_client, workspace):
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.get("/api/files", headers=headers)
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()["files"]]
    assert _rel(workspace, _own_output(workspace, "alice@cgiar.org", "tok1", "alice-report.txt")) in names
    # Neither Bob's file nor the legacy shared file is listed for a non-admin.
    assert not any("bob-report" in n for n in names)
    assert "outputs/report.txt" not in names


@pytest.mark.asyncio
async def test_list_files_admin_sees_legacy_but_not_other_users(auth_client, workspace):
    headers = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}
    names = [f["name"] for f in (await auth_client.get("/api/files", headers=headers)).json()["files"]]
    assert "outputs/report.txt" in names
    assert not any("bob-report" in n or "alice-report" in n for n in names)


@pytest.mark.asyncio
async def test_list_files_bypass_mode_no_token_needed(bypass_client):
    resp = await bypass_client.get("/api/files")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/files/{path} (download)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_401_no_auth_at_all(auth_client):
    resp = await auth_client.get("/api/files/outputs/report.txt")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_200_with_bearer_header(auth_client, workspace):
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    rel = _rel(workspace, _own_output(workspace, "alice@cgiar.org", "tok1", "alice-report.txt"))
    resp = await auth_client.get(f"/api/files/{rel}", headers=headers)
    assert resp.status_code == 200
    assert resp.content == b"alice report"


@pytest.mark.asyncio
async def test_download_other_users_file_is_404(auth_client, workspace):
    """Alice cannot open Bob's output even with the exact path (no oracle)."""
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    rel = _rel(workspace, _own_output(workspace, "bob@cgiar.org", "tok2", "bob-report.txt"))
    assert (await auth_client.get(f"/api/files/{rel}", headers=headers)).status_code == 404
    # ... nor as an administrator (admin rights never widen access, 2026-09-14)
    admin = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}
    assert (await auth_client.get(f"/api/files/{rel}", headers=admin)).status_code == 404


@pytest.mark.asyncio
async def test_legacy_shared_file_is_admin_only(auth_client):
    user = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    admin = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}
    assert (await auth_client.get("/api/files/outputs/report.txt", headers=user)).status_code == 404
    resp = await auth_client.get("/api/files/outputs/report.txt", headers=admin)
    assert resp.status_code == 200 and resp.content == b"hello report"


@pytest.mark.asyncio
async def test_hidden_database_never_served(auth_client, workspace):
    (workspace / ".synapsis").mkdir()
    (workspace / ".synapsis" / "chat.db").write_bytes(b"SQLite format 3")
    admin = {"Authorization": f"Bearer {_token_for('admin@cgiar.org', role='admin')}"}
    assert (await auth_client.get("/api/files/.synapsis/chat.db", headers=admin)).status_code == 404


@pytest.mark.asyncio
async def test_svg_is_never_served_inline(auth_client, workspace):
    """An SVG can carry script; it must download, never render (L1-05)."""
    svg = _own_output(workspace, "alice@cgiar.org", "tok3", "x.svg")
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.get(f"/api/files/{_rel(workspace, svg)}", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")
    png = _own_output(workspace, "alice@cgiar.org", "tok3", "chart.png")
    png.write_bytes(b"\x89PNG\r\n")
    resp = await auth_client.get(f"/api/files/{_rel(workspace, png)}", headers=headers)
    assert resp.headers["content-disposition"].startswith("inline")
    assert "sandbox" in resp.headers.get("content-security-policy", "")


@pytest.mark.asyncio
async def test_download_200_with_query_token(auth_client, workspace):
    """Plain <a href="/api/files/...?token=..."> links (no header) must work."""
    token = _token_for("alice@cgiar.org")
    rel = _rel(workspace, _own_output(workspace, "alice@cgiar.org", "tok1", "alice-report.txt"))
    resp = await auth_client.get(f"/api/files/{rel}?token={token}")
    assert resp.status_code == 200
    assert resp.content == b"alice report"


@pytest.mark.asyncio
async def test_download_401_invalid_query_token(auth_client):
    resp = await auth_client.get("/api/files/outputs/report.txt?token=not.a.jwt")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_bypass_mode_no_token_needed(bypass_client):
    resp = await bypass_client.get("/api/files/outputs/report.txt")
    assert resp.status_code == 200
    assert resp.content == b"hello report"


@pytest.mark.asyncio
async def test_download_traversal_rejected(workspace):
    """``../`` escape out of the workspace is rejected (403).

    Called directly against the route function (rather than through an HTTP
    client) because well-behaved HTTP clients (httpx included) normalize
    ``..`` dot-segments out of a URL *before* it is even sent — which would
    make this test pass for the wrong reason (a 404 from the SPA catch-all
    swallowing the un-normalized path, not from our traversal guard). This
    isolates the guard itself: a handler that receives a raw filename
    containing ``..`` (as it would from a raw-socket/lib client, curl
    ``--path-as-is``, or a future non-normalizing caller) must reject it.
    """
    from fastapi import HTTPException

    from synapsis.routes.files import download_file

    with patch("synapsis.routes.files.AUTH_DISABLED", True):
        with pytest.raises(HTTPException) as exc_info:
            await download_file("../workspace-secret/secret.txt")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_download_traversal_rejected_authenticated(workspace):
    """Same traversal guard holds when auth is enforced (Bearer supplied)."""
    from fastapi import HTTPException

    from synapsis.routes.files import download_file

    token = _token_for("alice@cgiar.org")
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.routes.files.AUTH_DISABLED", False),
    ):
        from synapsis.auth.tokens import verify_token
        header_user = verify_token(token)
        with pytest.raises(HTTPException) as exc_info:
            await download_file(
                "../workspace-secret/secret.txt", token=None, header_user=header_user
            )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_download_traversal_via_url_falls_through_to_spa_catchall(bypass_client):
    """Belt-and-suspenders HTTP-level check: an httpx client normalizes the
    ``..`` out of the URL before sending, so the request never even reaches
    ``/api/files/...`` -- it falls through to the SPA catch-all (200,
    index.html) rather than serving the secret file's bytes. Documents the
    client-side normalization behavior so it isn't mistaken for the real
    traversal guard (see the direct-call test above for that)."""
    resp = await bypass_client.get("/api/files/../workspace-secret/secret.txt")
    assert b"should never be reachable" not in resp.content


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_401_unauthenticated(auth_client):
    resp = await auth_client.post(
        "/api/upload", files={"file": ("test.txt", b"data", "text/plain")}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_200_with_token(auth_client, workspace):
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.post(
        "/api/upload",
        headers=headers,
        files={"file": ("test.txt", b"upload data", "text/plain")},
    )
    assert resp.status_code == 200
    from synapsis.user_files import owner_area
    dest = owner_area("uploads", "alice@cgiar.org", workspace) / "test.txt"
    assert dest.read_bytes() == b"upload data"
    assert resp.json()["path"] == str(dest)
    # The uploader can download it back; another user cannot.
    rel = _rel(workspace, dest)
    assert (await auth_client.get(f"/api/files/{rel}", headers=headers)).status_code == 200
    bob = {"Authorization": f"Bearer {_token_for('bob@cgiar.org')}"}
    assert (await auth_client.get(f"/api/files/{rel}", headers=bob)).status_code == 404


@pytest.mark.asyncio
async def test_upload_bypass_mode_no_token_needed(bypass_client, workspace):
    resp = await bypass_client.post(
        "/api/upload", files={"file": ("test2.txt", b"data2", "text/plain")}
    )
    assert resp.status_code == 200
    from synapsis.config import LEGACY_USER_ID
    from synapsis.user_files import owner_area
    assert (owner_area("uploads", LEGACY_USER_ID, workspace) / "test2.txt").read_bytes() == b"data2"
