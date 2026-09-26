"""
Shared pytest fixtures for the Synapsis backend test suite.

Environment pinning (review L7-06 / L7-09, 2026-09-26)
------------------------------------------------------
This module is imported by pytest BEFORE any test module, so the environment
is fixed here, before the first ``import synapsis``:

* ``SYNAPSIS_WORKSPACE`` -> a throw-away temp dir unless the caller set one.
  Importing ``synapsis`` creates the workspace; without the pin a plain
  ``pytest`` on the Mac would write into ``~/workspace``.
* ``IA_AUTH_DISABLED=false`` -> the suite always runs with authentication
  ENFORCED, exactly like every deployed environment. It used to follow the
  platform default (bypass on macOS, enforced on Linux), so 30 tests only
  passed on a Mac and nobody noticed. Tests that exercise the dev bypass patch
  ``AUTH_DISABLED`` explicitly.
* ``IA_JWT_SECRET`` -> a fixed test-only secret, so tokens minted by
  :func:`auth_headers` validate.
* Host leakage scrubbed: every other ``IA_*`` / ``SYNAPSIS_*`` variable (the
  Synapsis agent's own shell exports ``SYNAPSIS_MODEL=...`` etc.) and the
  provider keys are removed, so a test can never reach a paid API by accident.
  ``SYNAPSIS_PLATFORM`` (macOS vs prod-auth/Linux mode) and ``PRMS_DB_PATH``
  (the PRMS snapshot the data tests use) are deliberately kept.
  Set ``IA_TEST_KEEP_ENV=1`` to skip the scrub (debugging only).

Provides:
- tmp_db_path: A temporary SQLite database file path (cleaned up after each test).
- initialized_db: A fully-initialized database (all tables created via init_db())
  with DB_PATH and SYNAPSIS_DIR patched to use isolated temp directories.
- test_client: an ANONYMOUS httpx.AsyncClient wired to the FastAPI app with DB
  patching (auth enforced -> protected routes answer 401).
- auth_headers: factory for ``Authorization: Bearer`` headers of a synthetic
  identity (``auth_headers("researcher")``, ``auth_headers("admin", "x@y")``).
- admin_client / researcher_client: the same client, signed in as a synthetic
  admin / researcher.
- assert_json_response: Shared assertion helper for HTTP JSON responses.
"""

import atexit
import os
import shutil
import tempfile

# ---------------------------------------------------------------------------
# Environment pin -- MUST run before anything imports ``synapsis``.
# ---------------------------------------------------------------------------

#: Kept from the caller's environment on purpose (see module docstring).
_KEEP_ENV = {"SYNAPSIS_WORKSPACE", "SYNAPSIS_PLATFORM", "IA_TEST_KEEP_ENV"}
#: Provider credentials / host-agent variables that must never reach a test.
_SCRUB_EXTRA = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CLAUDECODE",
}
TEST_JWT_SECRET = "pytest-only-jwt-secret-not-used-anywhere-else"


def _pin_test_environment() -> None:
    if os.environ.get("IA_TEST_KEEP_ENV") != "1":
        for name in list(os.environ):
            if name in _KEEP_ENV:
                continue
            if name.startswith(("IA_", "SYNAPSIS_")) or name in _SCRUB_EXTRA:
                os.environ.pop(name, None)
    if not os.environ.get("SYNAPSIS_WORKSPACE"):
        workspace = tempfile.mkdtemp(prefix="ia-pytest-ws-")
        os.environ["SYNAPSIS_WORKSPACE"] = workspace
        atexit.register(shutil.rmtree, workspace, ignore_errors=True)
    os.environ["IA_AUTH_DISABLED"] = "false"
    os.environ["IA_JWT_SECRET"] = TEST_JWT_SECRET


_pin_test_environment()

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import patch

from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Pytest-asyncio configuration
# ---------------------------------------------------------------------------

# Use "auto" mode so all async tests in the suite get the asyncio event loop
# without having to decorate every single test function.
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="function")
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temporary SQLite database path inside a fresh temp directory.

    The ``tmp_path`` fixture is provided by pytest and is unique per-test, so
    each test gets a completely isolated database file.
    """
    synapsis_dir = tmp_path / ".synapsis"
    synapsis_dir.mkdir(parents=True, exist_ok=True)
    return synapsis_dir / "chat.db"


@pytest_asyncio.fixture(scope="function")
async def initialized_db(tmp_path: Path):
    """Yield an initialized database with all tables created.

    Patches ``synapsis.config.DB_PATH``, ``synapsis.config.SYNAPSIS_DIR``,
    ``synapsis.config.AUDIT_LOG``, and all the places those values are imported
    into (database module, audit module) so every call to ``get_db()`` or
    ``_get_shared_db()`` hits the temp database instead of the real one.

    Also resets the shared singleton connection (``_db``) between tests so each
    test gets a clean connection.

    Yields the Path to the temporary DB file for convenience.
    """
    synapsis_dir = tmp_path / ".synapsis"
    synapsis_dir.mkdir(parents=True, exist_ok=True)
    db_path = synapsis_dir / "chat.db"
    audit_log = synapsis_dir / "audit.log"

    with (
        patch("synapsis.config.DB_PATH", db_path),
        patch("synapsis.config.SYNAPSIS_DIR", synapsis_dir),
        patch("synapsis.config.AUDIT_LOG", audit_log),
        patch("synapsis.database.DB_PATH", db_path),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
        patch("synapsis.hooks.audit.AUDIT_LOG", audit_log),
        patch("synapsis.hooks.audit.SYNAPSIS_DIR", synapsis_dir),
    ):
        # Reset the shared singleton so it re-connects to the temp DB
        import synapsis.database as db_module
        db_module._db = None

        from synapsis.database import init_db
        await init_db()

        yield db_path

        # Teardown: close the shared connection so the temp file can be removed
        await db_module.close_db()


# ---------------------------------------------------------------------------
# Shared async test client (eliminates boilerplate in route tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def test_client(initialized_db):
    """Shared ANONYMOUS async test client with proper DB patching.

    Yields an httpx.AsyncClient wired to the FastAPI ASGI app so route tests
    can simply do ``response = await test_client.get("/api/health")`` without
    repeating the DB patch + app import + AsyncClient context-manager block.

    Authentication is enforced (see the environment pin above), so protected
    routes answer 401 here. Use ``admin_client`` / ``researcher_client`` or pass
    ``headers=auth_headers(...)`` for signed-in calls.
    """
    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# Authenticated clients (synthetic identities, test-only JWT secret)
# ---------------------------------------------------------------------------

#: Default synthetic identities. ``example.org`` addresses never match a real
#: account and the tokens are signed with ``TEST_JWT_SECRET`` only.
TEST_ADMIN_ID = "pytest-admin@example.org"
TEST_RESEARCHER_ID = "pytest-researcher@example.org"


def make_auth_headers(role: str = "researcher", user_id: str | None = None,
                      auth_source: str = "password") -> dict:
    """Return ``Authorization: Bearer`` headers for a synthetic identity.

    ``auth_source`` defaults to ``password`` because password login is enabled
    by default in the test configuration (``sso`` needs ``IA_SSO_ENABLED``).
    """
    from synapsis.auth.tokens import create_access_token

    uid = user_id or (TEST_ADMIN_ID if role == "admin" else TEST_RESEARCHER_ID)
    token = create_access_token(uid, uid.split("@")[0], role, auth_source=auth_source)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers():
    """Factory fixture: ``auth_headers("admin")``, ``auth_headers("researcher", "b@x.org")``."""
    return make_auth_headers


async def _client_with_headers(db_path: Path, headers: dict):
    with patch("synapsis.database.DB_PATH", db_path):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:
            yield client


@pytest_asyncio.fixture(scope="function")
async def admin_client(initialized_db):
    """Async test client signed in as a synthetic ADMIN (auth enforced)."""
    async for client in _client_with_headers(initialized_db, make_auth_headers("admin")):
        yield client


@pytest_asyncio.fixture(scope="function")
async def researcher_client(initialized_db):
    """Async test client signed in as a synthetic RESEARCHER (auth enforced)."""
    async for client in _client_with_headers(initialized_db, make_auth_headers("researcher")):
        yield client


# ---------------------------------------------------------------------------
# Shared assertion helpers
# ---------------------------------------------------------------------------

async def assert_json_response(response, status_code=200):
    """Assert response has expected status code and return parsed JSON.

    Usage in tests:
        data = await assert_json_response(resp)
        data = await assert_json_response(resp, status_code=201)
    """
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}. "
        f"Body: {response.text[:500]}"
    )
    return response.json()


async def assert_error_response(response, status_code=400):
    """Assert response is an error with the expected status code and return JSON."""
    assert response.status_code == status_code, (
        f"Expected error status {status_code}, got {response.status_code}. "
        f"Body: {response.text[:500]}"
    )
    return response.json()
