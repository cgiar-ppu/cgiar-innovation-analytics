"""
Synapsis-agent leftover routes are gone (review 2026-09-23 L7-05, L1-04,
L1-06, L6-07; lane A 2026-09-26).

Memories, workflows, workflow runs/logs, git, agent-query, skills, fleet,
images and /api/dashboard/stats were global across users (or replaced the IA
system prompt). They are no longer registered and must answer a clean JSON 404
— not the SPA's index.html — for every caller, admin included. The routes the
product needs (personas, PRMS dashboard, scope, files, sessions, export,
query, voice, TTS/transcribe) stay registered.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

def iter_routes(routes, prefix=""):
    """Yield (full_path, route) for every route, descending into included
    routers (FastAPI >= 0.13x keeps them as lazy ``_IncludedRouter`` entries
    whose own ``path`` is empty, so a flat ``app.routes`` scan misses them)."""
    for r in routes:
        ctx = getattr(r, "include_context", None)
        inner = getattr(r, "original_router", None)
        if ctx is not None and inner is not None:
            yield from iter_routes(inner.routes, prefix + (ctx.prefix or ""))
        else:
            yield prefix + getattr(r, "path", ""), r


def _all_paths(app) -> set[str]:
    return {p for p, _ in iter_routes(app.routes)}


REMOVED = [
    ("get", "/api/memories"),
    ("post", "/api/memories"),
    ("get", "/api/workflows"),
    ("post", "/api/workflows"),
    ("get", "/api/workflows/x/runs"),
    ("get", "/api/workflows/x/logs"),
    ("get", "/api/git/status"),
    ("get", "/api/git/log"),
    ("post", "/api/agents/orchestrator/query"),
    ("get", "/api/skills"),
    ("get", "/api/fleet"),
    ("post", "/api/fleet"),
    ("post", "/api/images/generate"),
    ("post", "/api/images/edit"),
    ("get", "/api/images/models"),
    ("get", "/api/dashboard/stats"),
]


def _admin_headers() -> dict:
    from synapsis.auth.tokens import create_access_token
    return {"Authorization": f"Bearer {create_access_token('admin@cgiar.org', 'admin', 'admin')}"}


@pytest.fixture
async def client(initialized_db: Path, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SPA</html>")
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.server._static_dir", static),
        patch("synapsis.server._index_html", static / "index.html"),
    ):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", REMOVED)
async def test_removed_routes_are_clean_404(client, method, path):
    resp = await getattr(client, method)(path, headers=_admin_headers())
    assert resp.status_code in (404, 405), (path, resp.status_code)
    assert "SPA" not in resp.text
    assert resp.headers["content-type"].startswith("application/json")


def test_removed_routes_are_not_in_the_app():
    from synapsis.server import app

    paths = _all_paths(app)
    for prefix in ("/api/memories", "/api/workflows", "/api/git", "/api/skills",
                   "/api/fleet", "/api/images", "/api/dashboard/stats"):
        assert not any(p.startswith(prefix) for p in paths), prefix
    assert "/api/agents/{agent_id}/query" not in paths


def test_product_routes_stay_registered():
    from synapsis.server import app

    paths = _all_paths(app)
    for needed in ("/api/personas", "/api/agents", "/api/files", "/api/files/{filename:path}",
                   "/api/upload", "/api/sessions", "/api/query", "/api/scope/options",
                   "/api/health", "/api/config", "/ws/chat"):
        assert needed in paths, needed
    assert any(p.startswith("/api/dashboard/prms") for p in paths)
    assert any(p.startswith("/api/voice") for p in paths)


@pytest.mark.asyncio
async def test_spa_still_serves_frontend_routes(client):
    for path in ("/", "/chat", "/settings"):
        resp = await client.get(path)
        assert resp.status_code == 200 and "SPA" in resp.text


def test_spa_catch_all_never_escapes_static(tmp_path):
    """uvicorn passes raw ``..`` segments through; the catch-all must not serve
    files outside static/ (found 2026-09-26; DEV nginx also blocks it)."""
    import asyncio

    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")

    with (
        patch("synapsis.server._static_dir", static),
        patch("synapsis.server._index_html", static / "index.html"),
    ):
        from synapsis.server import app

        async def raw(path: str):
            scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
                     "query_string": b"", "headers": [], "http_version": "1.1", "scheme": "http",
                     "server": ("t", 80), "client": ("c", 1), "root_path": ""}
            sent = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                sent.append(message)

            await app(scope, receive, send)
            return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")

        body = asyncio.run(raw("/../secret.txt"))
        assert b"TOP SECRET" not in body
