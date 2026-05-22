"""
Shared pytest fixtures for the Synapsis backend test suite.

Provides:
- tmp_db_path: A temporary SQLite database file path (cleaned up after each test).
- initialized_db: A fully-initialized database (all tables created via init_db())
  with DB_PATH and SYNAPSIS_DIR patched to use isolated temp directories.
- test_client: An httpx.AsyncClient wired to the FastAPI app with DB patching,
  eliminating the 3-line boilerplate repeated across route tests.
- assert_json_response: Shared assertion helper for HTTP JSON responses.
"""

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
    """Shared async test client with proper DB patching.

    Yields an httpx.AsyncClient wired to the FastAPI ASGI app so route tests
    can simply do ``response = await test_client.get("/api/agents")`` without
    repeating the DB patch + app import + AsyncClient context-manager block.
    """
    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
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
