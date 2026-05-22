"""Database connection management for the fleet database (fleet.db).

Provides the DatabaseManager instance and public connection helpers
(get_fleet_db, close_fleet_db) used by fleet operations.
"""

import synapsis.config as _config
from synapsis.db_manager import DatabaseManager

FLEET_DB_PATH = _config.SYNAPSIS_DIR / "fleet.db"

# ---------------------------------------------------------------------------
# DatabaseManager instance for the fleet database
# ---------------------------------------------------------------------------
# The lambda goes through the config module object so that test fixtures
# patching ``synapsis.config.SYNAPSIS_DIR`` are picked up at call time.

_manager = DatabaseManager(db_path_func=lambda: str(_config.SYNAPSIS_DIR / "fleet.db"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_fleet_db():
    """Async context manager for fleet database connections with row factory pre-configured.

    Opens a fresh aiosqlite connection for the duration of the ``async with``
    block, sets ``row_factory = aiosqlite.Row`` so columns are accessible by
    name, and guarantees the connection is closed on exit even if an exception
    is raised.

    Usage::

        async with get_fleet_db() as db:
            cursor = await db.execute("SELECT * FROM fleets")
            rows = await cursor.fetchall()

    Yields:
        An open :class:`aiosqlite.Connection` with row_factory configured.
    """
    return _manager.connect()


async def close_fleet_db() -> None:
    """Close the shared fleet database connection.

    Safe to call even if the connection was never opened.  After this call,
    the next connection request will open a fresh connection.
    Typically called from the FastAPI ``lifespan`` shutdown handler.
    """
    await _manager.close()
