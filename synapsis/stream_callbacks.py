"""StreamCallbacks -- dependency injection container for stream processing.

Allows the same streaming logic to serve both Chat (DB persistence, session-tagged
WebSocket) and Workflow (step_log accumulation, step-tagged WebSocket) without
code duplication.
"""

from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional


@dataclass
class StreamCallbacks:
    """Callbacks injected into shared streaming functions.

    Each path (Chat, Workflow) constructs its own StreamCallbacks instance
    that wires up the appropriate persistence and transport behavior.
    """

    # Send a message dict to the transport layer (WebSocket)
    send: Callable[[dict], Awaitable[None]]

    # Persist a message record
    # Chat: calls save_message(session_id, type, data)
    # Workflow: appends to step_log["messages"] and/or saves to workflow DB
    persist_message: Callable[[str, dict], Awaitable[None]]

    # Persist the Claude SDK session UUID
    # Chat: calls save_claude_session_id(session_id, uuid)
    # Workflow: sets step_log["session_id"]
    persist_session_id: Callable[[str], Awaitable[None]]

    # Called when a text block completes (Workflow accumulates for inter-step chaining)
    on_text_complete: Optional[Callable[[str], None]] = None

    # Extra fields injected into every outgoing message (e.g. {"step": 2} for Workflow)
    extra_fields: dict = field(default_factory=dict)

    # Whether this is the first init message (for Chat's duplicate suppression)
    # Chat manages this externally; workflow doesn't need it
    suppress_duplicate_init: bool = False

    async def emit(self, payload: dict) -> None:
        """Send a message with extra_fields automatically injected."""
        if self.extra_fields:
            payload = {**payload, **self.extra_fields}
        await self.send(payload)
