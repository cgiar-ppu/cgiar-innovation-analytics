"""
Connection registry -- WebSocket connection tracking.

Maintains the set of all active WebSocket connections and a per-session
registry that maps session_id to the set of send_json callables currently
viewing that session.  Used by the broadcast module to fan out messages.
"""


class ConnectionRegistry:
    """Tracks WebSocket connections globally and per-session."""

    def __init__(self) -> None:
        # All connected WebSocket send_json callables
        self._all_connections: set = set()
        # Maps session_id -> set of send_json callables viewing that session
        self._connection_registry: dict[str, set] = {}

    def register_connection(self, send_json_fn) -> None:
        """Register a WebSocket connection for global broadcasts."""
        self._all_connections.add(send_json_fn)

    def unregister_connection(self, send_json_fn) -> None:
        """Unregister a WebSocket connection from all registries."""
        self._all_connections.discard(send_json_fn)
        # Remove from all session-specific registries
        for viewers in self._connection_registry.values():
            viewers.discard(send_json_fn)

    def register_session_viewer(self, session_id: str, send_json_fn) -> None:
        """Register a connection as viewing a specific session."""
        if session_id not in self._connection_registry:
            self._connection_registry[session_id] = set()
        self._connection_registry[session_id].add(send_json_fn)

    def unregister_session_viewer(self, session_id: str, send_json_fn) -> None:
        """Unregister a connection from a specific session's viewer set."""
        viewers = self._connection_registry.get(session_id)
        if viewers:
            viewers.discard(send_json_fn)
            if not viewers:
                self._connection_registry.pop(session_id, None)

    def get_session_viewers(self, session_id: str) -> set:
        """Return the set of send_json callables viewing a session."""
        return self._connection_registry.get(session_id, set())

    @property
    def all_connections(self) -> set:
        """Return the set of all connected send_json callables."""
        return self._all_connections
