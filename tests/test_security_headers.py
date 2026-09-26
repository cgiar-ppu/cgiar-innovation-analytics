"""
HTTP hardening (review 2026-09-23 L1-07 CORS, L1-08/L4-11 headers + CSP,
L4-12 compression). No network, no model.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from synapsis.security_headers import (
    content_security_policy,
    cors_origins,
    cors_settings,
    static_security_headers,
)

DEV = "https://innovation-analytics-dev.synapsis-analytics.com"


def test_cors_defaults_to_the_env_origin_not_wildcard():
    assert cors_origins({"IA_SSO_ORIGIN": DEV + "/"}) == [DEV]
    assert cors_origins({}) == []
    assert cors_origins({"CORS_ORIGINS": "https://a.example, https://b.example"}) == [
        "https://a.example", "https://b.example"]
    s = cors_settings({"IA_SSO_ORIGIN": DEV})
    assert s["allow_origins"] == [DEV] and s["allow_credentials"] is True
    assert "*" not in s["allow_headers"] and "*" not in s["allow_methods"]


def test_cors_wildcard_is_never_combined_with_credentials():
    s = cors_settings({"CORS_ORIGINS": "*"})
    assert s["allow_origins"] == ["*"] and s["allow_credentials"] is False
    assert cors_settings({})["allow_credentials"] is False


def test_csp_report_only_by_default_and_tuned_for_the_spa():
    headers = dict(static_security_headers({"IA_SSO_ORIGIN": DEV}))
    ro = headers["content-security-policy-report-only"]
    assert headers["content-security-policy"] == "frame-ancestors 'none'"
    for needle in ("script-src 'self'", "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                   "font-src 'self' data: https://fonts.gstatic.com", "img-src 'self' data: blob:",
                   "wss://innovation-analytics-dev.synapsis-analytics.com", "frame-src 'self' blob: data:",
                   "object-src 'none'", "frame-ancestors 'none'", "mediastream:"):
        assert needle in ro, needle
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert "max-age=" in headers["strict-transport-security"]
    assert "microphone=(self)" in headers["permissions-policy"]


def test_csp_modes():
    enforce = dict(static_security_headers({"IA_CSP_MODE": "enforce"}))
    assert "content-security-policy-report-only" not in enforce
    assert enforce["content-security-policy"].startswith("default-src 'self'")
    off = dict(static_security_headers({"IA_CSP_MODE": "off"}))
    assert not any(k.startswith("content-security-policy") for k in off)
    assert content_security_policy({"IA_CSP_POLICY": "default-src 'none'"}) == "default-src 'none'"


@pytest.fixture
async def client(initialized_db: Path, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>SPA</html>")
    (static / "assets" / "app.js").write_text("console.log('x');" * 500)
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.server._static_dir", static),
        patch("synapsis.server._index_html", static / "index.html"),
    ):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_headers_on_api_spa_and_errors(client):
    for path in ("/api/health", "/", "/api/does-not-exist"):
        resp = await client.get(path)
        assert resp.headers["x-content-type-options"] == "nosniff", path
        assert resp.headers["x-frame-options"] == "DENY", path
        assert "content-security-policy-report-only" in resp.headers, path


@pytest.mark.asyncio
async def test_large_static_assets_are_gzipped(client):
    # When a real frontend build exists (static/ in the cwd at import time),
    # server.py mounts /assets from it and the fixture's patched _static_dir is
    # not consulted, so request the largest real asset instead of app.js.
    from starlette.routing import Mount
    from synapsis.server import app

    path = "/assets/app.js"
    mount = next((r for r in app.routes if isinstance(r, Mount) and r.path == "/assets"), None)
    if mount is not None:
        real = sorted(Path(mount.app.directory).glob("*.js"), key=lambda p: p.stat().st_size)
        if real and real[-1].stat().st_size >= 1024:
            path = "/assets/" + real[-1].name
    resp = await client.get(path, headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


@pytest.mark.asyncio
async def test_cross_origin_preflight_from_a_foreign_site_is_refused(client):
    resp = await client.options(
        "/api/sessions",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"
    assert resp.headers.get("access-control-allow-origin") != "*"
