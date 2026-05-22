"""
Broadcasting -- fan-out messages to WebSocket connections.

Provides the low-level ``_broadcast`` helper and the two public broadcast
functions (``broadcast_to_all`` and ``broadcast_to_session``) that the rest
of the codebase uses to notify connected clients.
"""

from synapsis.session.connection_registry import ConnectionRegistry


class Broadcaster:
    """Sends messages to sets of WebSocket connections."""

    def __init__(self, connection_registry: ConnectionRegistry) -> None:
        self._connections = connection_registry

    async def _broadcast(
        self, targets: set, message: dict, *, exclude=None, **send_kwargs
    ) -> None:
        """Send a message to a set of send_fn callables, ignoring closed connections."""
        for send_fn in list(targets):
            if send_fn is exclude:
                continue
            try:
                await send_fn(message, **send_kwargs)
            except (RuntimeError, ConnectionError):
                pass  # Connection may have closed between the state check and the send

    async def broadcast_to_session(
        self, session_id: str, message: dict, *, exclude=None
    ) -> None:
        """Send a message to all connections viewing a specific session, except the sender."""
        viewers = self._connections.get_session_viewers(session_id)
        await self._broadcast(viewers, message, exclude=exclude, sid=session_id)

    async def broadcast_to_all(self, message: dict, *, exclude=None) -> None:
        """Send a message to ALL connected WebSocket clients, except the sender."""
        await self._broadcast(self._connections.all_connections, message, exclude=exclude)
