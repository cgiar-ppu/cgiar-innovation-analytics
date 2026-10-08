"""Anonymous information leaks on /api/health, /api/activity, /api/config
(INT-3a note 2) and the configurable in-app contact (R-09, Lane E 3b).

- anonymous /api/health: status, git_sha, version, default model only
  (no model list, workspace path or auth method); admins get the full body;
- /api/activity requires a signed-in user;
- /api/config no longer carries the Synapsis leftovers memory_categories /
  vnc_available / vnc_port and serves the guardrail contacts (env-driven,
  technical default J.Berenguer@cgiar.org).
"""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _token(user_id: str, role: str) -> str:
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


@pytest.fixture
def auth_on():
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        yield


@pytest_asyncio.fixture
async def http(auth_on):
    from synapsis.server import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client


def _bearer(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(f'{role}@cgiar.org', role)}"}


@pytest.mark.asyncio
async def test_anonymous_health_keeps_deploy_fields_but_hides_models(http):
    r = await http.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    # Fields the deploy / release scripts read (deploy.yml, release-host.py).
    assert body["status"] == "ok" and "git_sha" in body and "version" in body
    assert isinstance(body["model"], str) and body["model"]
    for leaked in ("available_models", "workspace", "auth_method"):
        assert leaked not in body, leaked


@pytest.mark.asyncio
async def test_researcher_health_is_the_anonymous_shape(http):
    body = (await http.get("/api/health", headers=_bearer("researcher"))).json()
    assert "available_models" not in body and "workspace" not in body


@pytest.mark.asyncio
async def test_admin_health_carries_the_diagnostics(http):
    body = (await http.get("/api/health", headers=_bearer("admin"))).json()
    assert body["status"] == "ok"
    assert isinstance(body["available_models"], list) and body["available_models"]
    assert "workspace" in body and "auth_method" in body


@pytest.mark.asyncio
async def test_invalid_token_health_is_anonymous_not_an_error(http):
    r = await http.get("/api/health", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 200 and "available_models" not in r.json()


@pytest.mark.asyncio
async def test_activity_requires_a_signed_in_user(http):
    assert (await http.get("/api/activity")).status_code == 401
    r = await http.get("/api/activity", headers=_bearer("researcher"))
    assert r.status_code == 200
    assert "active_sessions" in r.json() or "active_connections" in r.json()


@pytest.mark.asyncio
async def test_config_drops_synapsis_leftovers(http):
    for headers in ({}, _bearer("researcher"), _bearer("admin")):
        body = (await http.get("/api/config", headers=headers)).json()
        for leftover in ("memory_categories", "vnc_available", "vnc_port"):
            assert leftover not in body, leftover
        # Fields the frontend still relies on stay.
        for key in ("model", "selectable_models", "model_policy", "sso_enabled",
                    "invited_login_enabled", "self_signup", "contacts"):
            assert key in body, key


@pytest.mark.asyncio
async def test_config_serves_default_contacts(http, monkeypatch):
    for var in ("IA_CONTACT_SCOPE_NAME", "IA_CONTACT_SCOPE_EMAIL",
                "IA_CONTACT_TECHNICAL_NAME", "IA_CONTACT_TECHNICAL_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    contacts = (await http.get("/api/config")).json()["contacts"]
    assert contacts == [
        {"name": "Marc Schut", "email": "marc.schut@cgiar.org", "remit": "scope & use"},
        {"name": "Jose Luis Berenguer", "email": "J.Berenguer@cgiar.org", "remit": "technical"},
    ]
    # The bounced address must never come back as a default.
    assert "synapsis-analytics.com" not in str(contacts)


@pytest.mark.asyncio
async def test_config_contacts_are_env_configurable(http, monkeypatch):
    monkeypatch.setenv("IA_CONTACT_TECHNICAL_EMAIL", "ia-support@example.org")
    monkeypatch.setenv("IA_CONTACT_TECHNICAL_NAME", "IA support desk")
    monkeypatch.setenv("IA_CONTACT_SCOPE_EMAIL", "")
    contacts = (await http.get("/api/config")).json()["contacts"]
    assert contacts == [{"name": "IA support desk", "email": "ia-support@example.org", "remit": "technical"}]


# ---------------------------------------------------------------------------
# QA-4 D15: anonymous /api/config internals and the public API docs
# ---------------------------------------------------------------------------

_INTERNALS = ("auth_method", "agent_type", "platform", "personas")
_PUBLIC = {"X-Forwarded-For": "203.0.113.7"}   # what every request through the ALB carries


@pytest.mark.asyncio
async def test_anonymous_config_has_no_internals(http):
    anon = (await http.get("/api/config")).json()
    for key in _INTERNALS:
        assert key not in anon, key
    # The login page still gets what it needs.
    for key in ("sso_enabled", "password_login_enabled", "invited_login_enabled", "self_signup",
                "signup_allowed_domains", "contacts", "model", "version"):
        assert key in anon, key
    forged = (await http.get("/api/config", headers={"Authorization": "Bearer not-a-jwt"})).json()
    assert not any(k in forged for k in _INTERNALS)


@pytest.mark.asyncio
async def test_signed_in_config_keeps_its_fields(http):
    body = (await http.get("/api/config", headers=_bearer("researcher"))).json()
    for key in _INTERNALS:
        assert key in body, key


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
async def test_api_docs_are_not_public(http, path):
    r = await http.get(path, headers=_PUBLIC)
    assert r.status_code == 404, path
    assert "<html" not in r.text.lower()           # not the SPA shell either
    r = await http.get(path, headers={**_PUBLIC, **_bearer("researcher")})
    assert r.status_code == 404, path


@pytest.mark.asyncio
async def test_admin_can_read_the_schema_through_the_proxy(http):
    r = await http.get("/openapi.json", headers={**_PUBLIC, **_bearer("admin")})
    assert r.status_code == 200 and "/api/config" in r.json()["paths"]
    assert (await http.get("/docs", headers={**_PUBLIC, **_bearer("admin")})).status_code == 404


@pytest.mark.asyncio
async def test_in_container_loopback_keeps_the_schema(http):
    """release-smoke.py walks /openapi.json anonymously from inside the container."""
    r = await http.get("/openapi.json")   # ASGI client = 127.0.0.1, no X-Forwarded-For
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/sessions" in paths and "/openapi.json" not in paths and "/docs" not in paths
    assert (await http.get("/docs")).status_code == 200


@pytest.mark.asyncio
async def test_local_dev_keeps_the_docs():
    from synapsis.server import app
    with patch("synapsis.auth.middleware.AUTH_DISABLED", True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/docs", headers=_PUBLIC)).status_code == 200
            assert (await c.get("/openapi.json", headers=_PUBLIC)).status_code == 200
