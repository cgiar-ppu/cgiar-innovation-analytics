"""Reusable database connection manager for aiosqlite.

Eliminates duplicated connection-management boilerplate between the database package
and workflow_db.py by encapsulating the dual-connection strategy (short-lived
context manager + long-lived shared singleton) in a single class.

Usage::

    from synapsis.db_manager import DatabaseManager

    _mgr = DatabaseManager(
        db_path_func=lambda: str(MY_DB_PATH),
        pragmas=["PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"],
    )

    # Short-lived connection (routes, tools)
    async with _mgr.connect() as db:
        ...

    # Long-lived singleton (internal helpers called on every chat turn)
    db = await _mgr.get_shared()
    ...

    # Shutdown
    await _mgr.close()
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Callable

import aiosqlite

_log = logging.getLogger("synapsis_agent")


class DatabaseManager:
    """Manages aiosqlite connections with optional PRAGMA configuration.

    Provides two access patterns:

    1. ``connect()`` -- async context manager yielding a fresh, short-lived
       connection.  Ideal for route handlers where you want automatic cleanup.

    2. ``get_shared()`` -- returns a process-wide singleton connection kept
       alive for the server lifetime.  Ideal for high-frequency internal
       helpers (e.g. save_message) that benefit from connection reuse.

    Args:
        db_path_func: A callable returning the database file path as a string.
                      Using a callable (rather than a bare string) allows the
                      path to be resolved lazily, which is useful when the
                      config module sets the path at import time.
        pragmas:      Optional list of PRAGMA SQL statements to execute on
                      every new connection (e.g. ``["PRAGMA journal_mode=WAL"]``).
        timeout:      Connection timeout in seconds (passed to aiosqlite).
        wal:          Put the database in WAL journal mode when the shared
                      connection is opened (best effort; WAL is persistent in
                      the file, so this is a no-op after the first time).

    Writes on the shared connection should go through :meth:`shared_write`,
    which serialises them with an ``asyncio.Lock`` and commits on success /
    rolls back on ANY exception including task cancellation. Without it a
    streaming task cancelled between ``execute`` and ``commit`` left a write
    transaction open on the process-wide connection, blocking every other
    writer for up to ``timeout`` seconds (L3-10; same pattern as the Synapsis
    incident of 2026-09-10).
    """

    def __init__(
        self,
        db_path_func: Callable[[], str],
        pragmas: Optional[list[str]] = None,
        timeout: float = 30.0,
        wal: bool = False,
    ):
        self._db: Optional[aiosqlite.Connection] = None
        self._get_path = db_path_func
        self._pragmas = pragmas or []
        self._timeout = timeout
        self._wal = wal
        self._write_lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Execute configured PRAGMA statements on *db*."""
        for pragma in self._pragmas:
            await db.execute(pragma)

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Context manager for short-lived connections.

        Opens a fresh aiosqlite connection, configures ``row_factory`` and
        pragmas, yields it, then closes on exit.

        Yields:
            An open :class:`aiosqlite.Connection` with row_factory configured.
        """
        async with aiosqlite.connect(self._get_path(), timeout=self._timeout) as db:
            db.row_factory = aiosqlite.Row
            await self._apply_pragmas(db)
            yield db

    async def get_shared(self) -> aiosqlite.Connection:
        """Get or create a long-lived shared connection.

        Returns a singleton aiosqlite connection with ``row_factory`` set.
        Created on first call and reused for all subsequent calls.

        Returns:
            The open aiosqlite connection.
        """
        if self._db is None:
            db = await aiosqlite.connect(self._get_path(), timeout=self._timeout)
            db.row_factory = aiosqlite.Row
            await self._apply_pragmas(db)
            if self._wal:
                try:
                    await db.execute("PRAGMA journal_mode=WAL")
                except Exception:
                    _log.warning("Could not switch %s to WAL mode", self._get_path(), exc_info=True)
            self._db = db
        return self._db

    def _get_write_lock(self) -> asyncio.Lock:
        """The shared-connection write lock, bound to the running event loop."""
        loop = asyncio.get_running_loop()
        if self._write_lock is None or self._lock_loop is not loop:
            self._write_lock = asyncio.Lock()
            self._lock_loop = loop
        return self._write_lock

    @staticmethod
    async def _safe_rollback(db: aiosqlite.Connection) -> None:
        try:
            # Shield so a second cancellation cannot abandon the rollback.
            await asyncio.shield(db.rollback())
        except BaseException:  # noqa: BLE001 - best effort; caller re-raises
            _log.debug("Rollback on shared connection failed", exc_info=True)

    @asynccontextmanager
    async def shared_write(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Serialised write transaction on the shared connection.

        Usage::

            async with mgr.shared_write() as db:
                await db.execute("INSERT ...")
                await db.execute("UPDATE ...")
            # committed here; rolled back if the block raised or was cancelled
        """
        async with self._get_write_lock():
            db = await self.get_shared()
            try:
                yield db
            except BaseException:
                await self._safe_rollback(db)
                raise
            try:
                await db.commit()
            except BaseException:
                await self._safe_rollback(db)
                raise

    async def close(self) -> None:
        """Close the shared connection.

        Safe to call even if the connection was never opened.  After this
        call, the next ``get_shared()`` invocation will create a fresh
        connection.
        """
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None
        self._write_lock = None
        self._lock_loop = None
