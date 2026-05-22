"""Chat Run Manager -- manages chat task lifecycles independently of WebSocket connections.

Each chat session has at most ONE active task at a time. WebSocket connections
attach/detach as subscribers without affecting the running task. Starting a new
task for a session that already has one will cancel the existing task first.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from synapsis.config import logger
from synapsis.constants import (
    CHAT_DETACHED_TASK_TIMEOUT,
    CHAT_EVENT_BUFFER_MAX,
    CHAT_RUN_RETENTION_SECONDS,
    CHAT_SUBSCRIBER_QUEUE_SIZE,
)


@dataclass
class ChatRunHandle:
    """Represents a running or recently-completed chat task for a session."""

    session_id: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: Optional[asyncio.Task] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    event_buffer: list = field(default_factory=list)
    subscribers: list = field(default_factory=list)  # list[asyncio.Queue]
    status: str = "running"  # running, completed, cancelled, failed
    started_at: float = field(default_factory=time.time)
    client: Optional[Any] = None  # ClaudeSDKClient reference for teardown
    _session_complete_emitted: bool = False  # Guard: ensures session_complete fires only once per run
    _retention_timer: Optional[asyncio.TimerHandle] = field(default=None, repr=False)


def _cap_event_buffer(handle: ChatRunHandle) -> None:
    """Trim the event buffer to its maximum allowed size."""
    if len(handle.event_buffer) > CHAT_EVENT_BUFFER_MAX:
        handle.event_buffer = handle.event_buffer[-CHAT_EVENT_BUFFER_MAX:]


def _fan_out_event(handle: ChatRunHandle, event: dict, session_id: str) -> None:
    """Push an event to all subscriber queues, removing broken ones."""
    disconnected: list[int] = []
    for i, queue in enumerate(handle.subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Subscriber queue full for session %s", session_id)
        except Exception:
            disconnected.append(i)
    for i in reversed(disconnected):
        handle.subscribers.pop(i)


def _schedule_retention_cleanup(
    manager: "ChatRunManager",
    handle: ChatRunHandle,
    session_id: str,
) -> None:
    """Schedule removal of a completed handle after the retention period."""
    try:
        loop = asyncio.get_running_loop()
        handle_ref = handle  # capture for the closure

        def _retention_pop(sid: str = session_id) -> None:
            if manager._handles.get(sid) is handle_ref:
                manager._handles.pop(sid, None)

        handle._retention_timer = loop.call_later(
            CHAT_RUN_RETENTION_SECONDS,
            _retention_pop,
        )
    except RuntimeError:
        # No running loop (shutting down) -- just leave it
        pass


class ChatRunManager:
    """Singleton that owns chat task lifecycles independently of WebSocket connections.

    Key invariant: at most one running task per session_id. Starting a new task
    for a session that already has one will cancel the existing task first.
    """

    def __init__(self) -> None:
        self._handles: dict[str, ChatRunHandle] = {}
        self._detach_timers: dict[str, asyncio.TimerHandle] = {}

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    async def start_task(self, session_id: str, coro, *, client: Any = None) -> ChatRunHandle:
        """Register and start a streaming coroutine as a managed task.

        If a task already exists for this session, it is cancelled first.

        Args:
            session_id: The chat session identifier.
            coro:       A callable ``async def coro(send_event, cancel_event)``
                        that performs the streaming work.
            client:     Optional SDK client reference stored on the handle for
                        teardown during cancellation.

        Returns:
            The newly created ChatRunHandle.
        """
        # Cancel any existing task for this session
        existing = self._handles.get(session_id)
        if existing:
            if existing._retention_timer is not None:
                existing._retention_timer.cancel()
                existing._retention_timer = None
            if existing.status == "running":
                logger.info("Cancelling existing task for session %s before starting new one", session_id)
                await self.cancel(session_id)

        handle = ChatRunHandle(session_id=session_id, client=client)

        # Build the send_event callback that buffers + fans out
        async def send_event(event: dict, *, sid: str | None = None) -> None:
            event["session_id"] = session_id
            event["run_id"] = handle.run_id
            handle.event_buffer.append(event)
            _cap_event_buffer(handle)
            _fan_out_event(handle, event, session_id)

        # Wrap the coroutine so we can track completion status
        async def run_task() -> None:
            try:
                await coro(send_event, handle.cancel_event)
                handle.status = "completed"
            except asyncio.CancelledError:
                handle.status = "cancelled"
                logger.info("Chat task for session %s was cancelled", session_id)
            except Exception as e:
                handle.status = "failed"
                logger.exception("Chat task for session %s failed: %s", session_id, e)
            finally:
                self._finalize_task(handle, session_id)

        handle.task = asyncio.create_task(run_task())
        self._handles[session_id] = handle

        # Cancel any pending detach timer for this session
        timer = self._detach_timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

        logger.info("Started chat task for session %s", session_id)
        return handle

    def _finalize_task(self, handle: ChatRunHandle, session_id: str) -> None:
        """Send the terminal status event and schedule retention cleanup."""
        terminal_event = {
            "type": "task_status",
            "session_id": session_id,
            "run_id": handle.run_id,
            "status": handle.status,
        }
        handle.event_buffer.append(terminal_event)
        _cap_event_buffer(handle)
        for queue in handle.subscribers:
            try:
                queue.put_nowait(terminal_event)
            except Exception:
                pass

        _schedule_retention_cleanup(self, handle, session_id)

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def attach(self, session_id: str) -> Optional[tuple[list, asyncio.Queue]]:
        """Attach a subscriber to a chat session's event stream.

        Returns ``(buffered_events, live_queue)`` or ``None`` if no handle
        exists for the session.
        """
        handle = self._handles.get(session_id)
        if not handle:
            return None

        queue: asyncio.Queue = asyncio.Queue(maxsize=CHAT_SUBSCRIBER_QUEUE_SIZE)
        handle.subscribers.append(queue)

        # Cancel any pending detach timer since we now have a subscriber
        timer = self._detach_timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

        # Only replay events from the current (in-progress) turn.
        replay_events = _compute_replay_events(handle)
        return replay_events, queue

    def detach(self, session_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue from a session. Does NOT cancel the task."""
        handle = self._handles.get(session_id)
        if not handle:
            return
        try:
            handle.subscribers.remove(queue)
        except ValueError:
            pass

        # Start detached-task timeout if no subscribers remain and task is running
        if not handle.subscribers and handle.status == "running":
            self._start_detach_timer(session_id)

    def _start_detach_timer(self, session_id: str) -> None:
        """Schedule auto-cancellation for a detached task with no subscribers."""
        timer = self._detach_timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

        try:
            loop = asyncio.get_running_loop()

            def on_timeout() -> None:
                self._detach_timers.pop(session_id, None)
                handle = self._handles.get(session_id)
                if handle and handle.status == "running" and not handle.subscribers:
                    logger.warning(
                        "Auto-cancelling detached chat task for session %s "
                        "(no subscribers for %ds)",
                        session_id,
                        CHAT_DETACHED_TASK_TIMEOUT,
                    )
                    asyncio.ensure_future(self.cancel(session_id))

            self._detach_timers[session_id] = loop.call_later(
                CHAT_DETACHED_TASK_TIMEOUT, on_timeout
            )
        except RuntimeError:
            pass  # No running loop

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def cancel(self, session_id: str) -> bool:
        """Cancel a running chat task for the given session.

        Returns:
            True if cancellation was initiated, False if no running task found.
        """
        handle = self._handles.get(session_id)
        if not handle or handle.status != "running":
            return False

        handle.cancel_event.set()

        if handle.task and not handle.task.done():
            handle.task.cancel()
            try:
                await asyncio.wait_for(handle.task, timeout=10.0)
            except asyncio.TimeoutError:
                handle.status = "cancelled"
            except asyncio.CancelledError:
                pass
        else:
            handle.status = "cancelled"

        # Cancel any detach timer
        timer = self._detach_timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

        logger.info("Cancelled chat task for session %s (status=%s)", session_id, handle.status)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_handle(self, session_id: str) -> Optional[ChatRunHandle]:
        """Get the ChatRunHandle for a session, or None if not found."""
        return self._handles.get(session_id)

    def is_running(self, session_id: str) -> bool:
        """Check if a chat task is currently running for the given session."""
        handle = self._handles.get(session_id)
        return handle is not None and handle.status == "running"

    def try_mark_session_complete(self, session_id: str, run_id: str | None = None) -> bool:
        """Atomically check and set the session_complete guard flag.

        Returns True if this is the FIRST call for this run (caller should
        emit session_complete). Returns False if session_complete was already
        emitted or if the run_id doesn't match (stale request from a previous run).
        """
        handle = self._handles.get(session_id)
        if not handle:
            return True  # No handle -- let the caller emit (best-effort)
        if run_id and handle.run_id != run_id:
            return False  # Stale request from a previous run
        if handle._session_complete_emitted:
            return False
        handle._session_complete_emitted = True
        return True

    def set_client(self, session_id: str, client: Any) -> None:
        """Store the SDK client reference on the handle so cancel can tear it down."""
        handle = self._handles.get(session_id)
        if handle:
            handle.client = client

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all running chat tasks. Called on app shutdown."""
        for session_id in list(self._handles.keys()):
            await self.cancel(session_id)

        for timer in self._detach_timers.values():
            timer.cancel()
        self._detach_timers.clear()

        self._handles.clear()
        logger.info("Chat run manager shut down")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _compute_replay_events(handle: ChatRunHandle) -> list:
    """Return the subset of buffered events to replay for a late-joining subscriber.

    Events before the last 'result' event are already persisted in the
    database and will be loaded via loadHistory(). Replaying them would
    cause duplicate messages in the frontend.
    """
    last_result_idx = -1
    for i, event in enumerate(handle.event_buffer):
        if event.get("type") in ("result", "session_complete"):
            last_result_idx = i

    if last_result_idx >= 0:
        return handle.event_buffer[last_result_idx + 1:]
    return list(handle.event_buffer)


# Singleton instance
chat_run_manager = ChatRunManager()
