"""
SessionManager -- composes client registry, connection registry, broadcaster,
and cancel manager into a single facade that preserves the original API.

All module-level wrapper functions in ``synapsis.session_manager`` (and
``synapsis.session.__init__``) delegate to the singleton instance of this
class.
"""

import asyncio
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient

from synapsis.config import logger
from synapsis.constants import IDLE_SESSION_REAPER_INTERVAL
from synapsis.session.client_registry import ClientRegistry
from synapsis.session.connection_registry import ConnectionRegistry
from synapsis.session.broadcast import Broadcaster
from synapsis.session.cancel import CancelManager


class SessionManager:
    """Encapsulates all shared session state and lifecycle operations.

    Instantiate once at module level (``session_manager = SessionManager()``)
    and use the module-level wrapper functions for backward-compatible access.
    """

    def __init__(self) -> None:
        # Compose the focused registries
        self._client_registry = ClientRegistry()
        self._connection_registry = ConnectionRegistry()
        self._broadcaster = Broadcaster(self._connection_registry)
        self._cancel_manager = CancelManager(self._client_registry)

        # WebSocket connection counter (used by Lambda keep-alive health checks)
        self._active_websockets: int = 0

        # Timestamp of the most recent WebSocket activity (send or receive)
        self._last_activity: float = 0.0

        # Lock protecting concurrent modifications to _active_websockets and _last_activity
        self._session_lock: asyncio.Lock = asyncio.Lock()

        # Background reaper task (started lazily via start_reaper)
        self._reaper_task: Optional[asyncio.Task] = None

    # -- Expose the sessions dict directly for backward compatibility ----------
    @property
    def sessions(self) -> dict[str, ClaudeSDKClient]:
        return self._client_registry.sessions

    # -- Expose internal _session_locks for backward compat (release_session_client reads it) --
    @property
    def _session_locks(self) -> dict[str, asyncio.Lock]:
        return self._client_registry._session_locks

    # -------------------------------------------------------------------
    # Activity tracking
    # -------------------------------------------------------------------

    def has_active_connections(self) -> bool:
        """Return True if at least one WebSocket connection is open."""
        return self._active_websockets > 0

    def get_last_activity(self) -> float:
        """Return the Unix timestamp of the last WebSocket activity."""
        return self._last_activity

    def get_activity_stats(self) -> dict:
        """Return a snapshot of connection stats for the health/activity endpoint."""
        return {
            "active_connections": self._active_websockets,
            "last_activity": self._last_activity,
            "active_sessions": len(self.sessions),
        }

    async def increment_connections(self) -> None:
        """Increment the active WebSocket connection counter (called on accept)."""
        async with self._session_lock:
            self._active_websockets += 1

    async def decrement_connections(self) -> None:
        """Decrement the connection counter, clamped to 0 (called on disconnect)."""
        async with self._session_lock:
            self._active_websockets = max(0, self._active_websockets - 1)

    async def record_activity(self, ts: float) -> None:
        """Record a WebSocket activity timestamp (called on send/receive)."""
        async with self._session_lock:
            self._last_activity = ts

    # -------------------------------------------------------------------
    # Client registry delegation
    # -------------------------------------------------------------------

    def get_session_lock(self, session_id: str) -> asyncio.Lock:
        return self._client_registry.get_session_lock(session_id)

    async def acquire_session_client(
        self, session_id: str, sessions_dict: dict,
    ) -> tuple["ClaudeSDKClient", bool]:
        return await self._client_registry.acquire_session_client(session_id, sessions_dict)

    def release_session_client(self, session_id: str) -> None:
        return self._client_registry.release_session_client(session_id)

    def is_session_busy(self, session_id: str) -> bool:
        return self._client_registry.is_session_busy(session_id)

    def cleanup_done_tasks(self, *args, **kwargs) -> None:
        return self._client_registry.cleanup_done_tasks(*args, **kwargs)

    async def _resume_or_create_client(
        self, session_id: str, sessions_dict: dict,
    ) -> ClaudeSDKClient:
        return await self._client_registry._resume_or_create_client(session_id, sessions_dict)

    async def _create_and_connect_client(
        self, resume_session_id: Optional[str] = None,
    ) -> ClaudeSDKClient:
        return await self._client_registry._create_and_connect_client(resume_session_id)

    async def cleanup_session_client(self, session_id: str) -> None:
        return await self._client_registry.cleanup_session_client(session_id)

    async def cleanup_orphaned_sessions(self) -> int:
        """Clean up sessions with no WebSocket viewers and no active task.

        Called after a WebSocket disconnects to reap subprocess resources.
        Returns the number of sessions cleaned up.
        """
        cleaned = 0
        for sid in list(self._client_registry.sessions):
            viewers = self._connection_registry.get_session_viewers(sid)
            busy = self._client_registry.is_session_busy(sid)
            if not viewers and not busy:
                logger.info(
                    "Cleaning up orphaned session %s (no viewers, not busy)",
                    sid,
                )
                await self._client_registry.cleanup_session_client(sid)
                cleaned += 1
        if cleaned:
            logger.info("Cleaned up %d orphaned session(s)", cleaned)
        return cleaned

    # -------------------------------------------------------------------
    # Background idle session reaper
    # -------------------------------------------------------------------

    def start_reaper(self) -> None:
        """Start the background idle session reaper.

        Called once at app startup.  The reaper runs every
        ``IDLE_SESSION_REAPER_INTERVAL`` seconds and cleans up sessions
        whose CLI subprocesses are no longer needed.
        """
        if self._reaper_task is not None:
            return  # Already running

        async def _reaper_loop() -> None:
            logger.info(
                "Idle session reaper started (interval=%ds)",
                IDLE_SESSION_REAPER_INTERVAL,
            )
            while True:
                try:
                    await asyncio.sleep(IDLE_SESSION_REAPER_INTERVAL)
                    await self.cleanup_orphaned_sessions()
                    # Also reap dead subprocesses (exited but still in sessions dict)
                    reaped = 0
                    for sid in list(self._client_registry.sessions):
                        client = self._client_registry.sessions[sid]
                        if not self._client_registry._is_client_alive(client):
                            logger.info(
                                "Reaper: removing dead subprocess for session %s", sid
                            )
                            await self._client_registry.cleanup_session_client(sid)
                            reaped += 1
                    if reaped:
                        logger.info("Reaper: removed %d dead subprocess(es)", reaped)
                except asyncio.CancelledError:
                    logger.info("Idle session reaper stopped")
                    return
                except Exception:
                    logger.exception("Error in idle session reaper (continuing)")

        self._reaper_task = asyncio.create_task(_reaper_loop())

    async def stop_reaper(self) -> None:
        """Stop the background reaper task (called on shutdown)."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None

    # -------------------------------------------------------------------
    # Client registry delegation (continued)
    # -------------------------------------------------------------------

    async def handle_new_session(
        self, sessions_dict: dict, send_json,
    ) -> tuple[str, ClaudeSDKClient]:
        return await self._client_registry.handle_new_session(sessions_dict, send_json)

    async def handle_switch_session(
        self, payload: dict, sessions_dict: dict, send_json,
    ) -> Optional[tuple[str, ClaudeSDKClient]]:
        return await self._client_registry.handle_switch_session(payload, sessions_dict, send_json)

    async def ensure_session(
        self, session_id: Optional[str], user_message: str, sessions_dict: dict,
    ) -> tuple[str, ClaudeSDKClient]:
        return await self._client_registry.ensure_session(session_id, user_message, sessions_dict)

    # -------------------------------------------------------------------
    # Connection registry delegation
    # -------------------------------------------------------------------

    def register_connection(self, send_json_fn) -> None:
        return self._connection_registry.register_connection(send_json_fn)

    def unregister_connection(self, send_json_fn) -> None:
        return self._connection_registry.unregister_connection(send_json_fn)

    def register_session_viewer(self, session_id: str, send_json_fn) -> None:
        return self._connection_registry.register_session_viewer(session_id, send_json_fn)

    def unregister_session_viewer(self, session_id: str, send_json_fn) -> None:
        return self._connection_registry.unregister_session_viewer(session_id, send_json_fn)

    # -------------------------------------------------------------------
    # Broadcast delegation
    # -------------------------------------------------------------------

    async def _broadcast(
        self, targets: set, message: dict, *, exclude=None, **send_kwargs,
    ) -> None:
        return await self._broadcaster._broadcast(targets, message, exclude=exclude, **send_kwargs)

    async def broadcast_to_session(
        self, session_id: str, message: dict, *, exclude=None,
    ) -> None:
        return await self._broadcaster.broadcast_to_session(session_id, message, exclude=exclude)

    async def broadcast_to_all(self, message: dict, *, exclude=None) -> None:
        return await self._broadcaster.broadcast_to_all(message, exclude=exclude)

    # -------------------------------------------------------------------
    # Cancel delegation
    # -------------------------------------------------------------------

    async def cancel_existing_task(self, session_id: Optional[str]) -> None:
        return await self._cancel_manager.cancel_existing_task(session_id)

    async def handle_cancel(
        self,
        session_id: Optional[str],
        client: Optional[ClaudeSDKClient],
        sessions_dict: dict,
        send_json,
    ) -> None:
        return await self._cancel_manager.handle_cancel(
            session_id, client, sessions_dict, send_json,
        )
