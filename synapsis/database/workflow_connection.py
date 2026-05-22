"""Connection management for the workflow runs database."""

import aiosqlite

from synapsis.config import SYNAPSIS_DIR, logger
from synapsis.db_manager import DatabaseManager

WORKFLOW_DB_PATH = str(SYNAPSIS_DIR / "workflow_runs.db")

# ---------------------------------------------------------------------------
# DatabaseManager instance for the workflow runs database
# ---------------------------------------------------------------------------

_manager = DatabaseManager(
    db_path_func=lambda: WORKFLOW_DB_PATH,
    pragmas=["PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"],
)


def get_workflow_db():
    """Async context manager for workflow database connections with row factory pre-configured.

    Opens a fresh aiosqlite connection for the duration of the ``async with``
    block, sets ``row_factory = aiosqlite.Row`` so columns are accessible by
    name, enables WAL mode and foreign keys, and guarantees the connection is
    closed on exit even if an exception is raised.

    Usage::

        async with get_workflow_db() as db:
            cursor = await db.execute("SELECT * FROM workflow_runs")
            rows = await cursor.fetchall()

    Yields:
        An open :class:`aiosqlite.Connection` with row_factory configured.
    """
    return _manager.connect()


async def _get_shared_workflow_db() -> aiosqlite.Connection:
    """Get or create the process-wide shared workflow database connection.

    Returns a singleton aiosqlite connection with row_factory set so rows can
    be accessed by column name.  The connection is created on first call and
    reused for all subsequent calls within the same process lifetime.

    This is intentionally module-private (prefixed with ``_``).  External
    callers should use the ``get_workflow_db()`` context manager instead.

    Returns:
        The open aiosqlite connection.
    """
    return await _manager.get_shared()


async def close_workflow_db() -> None:
    """Close the shared workflow database connection.

    Safe to call even if the connection was never opened.  After this call,
    the next ``_get_shared_workflow_db()`` invocation will open a fresh
    connection.  Typically called from the FastAPI ``lifespan`` shutdown handler.
    """
    await _manager.close()
