"""Tests for the files API auth gap fix (2026-07-20).

Covers:
- GET /api/files: 401 unauthenticated, 200 with a valid Bearer token.
- GET /api/files/{path}: 401 with neither header nor ?token=, 200 with a
  Bearer header, 200 with ?token= (the plain-<a>-link path), and a rejected
  ``../`` path-traversal escape.
- POST /api/upload: 401 unauthenticated, 200 with a valid Bearer token.
- Dev-bypass mode (AUTH_DISABLED=True, the local macOS default): all three
  endpoints work with no token at all, matching every other route.
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport


def _token_for(user_id: str, role: str = "user") -> str:
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


@pytest.fixture
def workspace(tmp_path):
    """A throwaway workspace dir with one seeded file, patched into files.py."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "outputs").mkdir()
    (ws / "outputs" / "report.txt").write_text("hello report")
    # A secret sibling directory OUTSIDE the workspace whose name shares a
    # string prefix with it -- proves the traversal check is boundary-exact,
    # not a naive str.startswith.
    sibling = tmp_path / "workspace-secret"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("should never be reachable")
    with patch("synapsis.routes.files.WORKSPACE", ws):
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
async def test_list_files_200_with_token(auth_client):
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.get("/api/files", headers=headers)
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()["files"]]
    assert "outputs/report.txt" in names


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
async def test_download_200_with_bearer_header(auth_client):
    headers = {"Authorization": f"Bearer {_token_for('alice@cgiar.org')}"}
    resp = await auth_client.get("/api/files/outputs/report.txt", headers=headers)
    assert resp.status_code == 200
    assert resp.content == b"hello report"


@pytest.mark.asyncio
async def test_download_200_with_query_token(auth_client):
    """Plain <a href="/api/files/...?token=..."> links (no header) must work."""
    token = _token_for("alice@cgiar.org")
    resp = await auth_client.get(f"/api/files/outputs/report.txt?token={token}")
    assert resp.status_code == 200
    assert resp.content == b"hello report"


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
    assert (workspace / "uploads" / "test.txt").read_bytes() == b"upload data"


@pytest.mark.asyncio
async def test_upload_bypass_mode_no_token_needed(bypass_client, workspace):
    resp = await bypass_client.post(
        "/api/upload", files={"file": ("test2.txt", b"data2", "text/plain")}
    )
    assert resp.status_code == 200
    assert (workspace / "uploads" / "test2.txt").read_bytes() == b"data2"
