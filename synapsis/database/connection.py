"""Database connection management for the main chat database.

Provides the DatabaseManager instance and public connection helpers
(get_db, _get_shared_db, close_db) used throughout the application.
"""

import aiosqlite

import synapsis.config as _config
from synapsis.config import DB_PATH, SYNAPSIS_DIR, logger
from synapsis.db_manager import DatabaseManager


# ---------------------------------------------------------------------------
# DatabaseManager instance for the main chat database
# ---------------------------------------------------------------------------
# The lambda goes through the config module object so that test fixtures
# patching ``synapsis.config.DB_PATH`` are picked up at call time.

_manager = DatabaseManager(db_path_func=lambda: str(_config.DB_PATH))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_db():
    """Async context manager for database connections with row factory pre-configured.

    Opens a fresh aiosqlite connection for the duration of the ``async with``
    block, sets ``row_factory = aiosqlite.Row`` so columns are accessible by
    name, and guarantees the connection is closed on exit even if an exception
    is raised.

    Usage::

        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM sessions")
            rows = await cursor.fetchall()

    Yields:
        An open :class:`aiosqlite.Connection` with row_factory configured.
    """
    return _manager.connect()


async def _get_shared_db() -> aiosqlite.Connection:
    """Get or create the process-wide shared database connection.

    Returns a singleton aiosqlite connection with row_factory set so rows can
    be accessed by column name.  The connection is created on first call and
    reused for all subsequent calls within the same process lifetime.

    This is intentionally module-private (prefixed with ``_``).  External
    callers should use the ``get_db()`` context manager instead.

    Returns:
        The open aiosqlite connection.
    """
    return await _manager.get_shared()


async def close_db() -> None:
    """Close the shared database connection.

    Safe to call even if the connection was never opened.  After this call,
    the next ``_get_shared_db()`` invocation will open a fresh connection.
    Typically called from the FastAPI ``lifespan`` shutdown handler.
    """
    await _manager.close()
