"""
Shared WebSocket utilities used by both websocket.py and workflow_ws.py.

Extracts common patterns:
  - forward_events()     -- pump events from an asyncio.Queue to a send function
  - stop_forward_task()  -- cancel a forwarding task and await its cleanup
  - detach_and_stop()    -- detach a subscriber queue from a run manager and stop forwarding
"""

import asyncio
from typing import Any, Callable, Awaitable, Optional


async def forward_events(
    queue: asyncio.Queue,
    send_fn: Callable[[dict], Awaitable[None]],
    *,
    check_connected: Optional[Callable[[], bool]] = None,
) -> None:
    """Forward events from a subscriber queue to a WebSocket send function.

    Reads events from *queue* in an infinite loop and passes each to *send_fn*.
    The loop exits cleanly on ``CancelledError`` (the normal shutdown path) or
    when *check_connected* returns ``False`` (optional early-exit for raw
    WebSocket sends that need a connection-state guard).

    Args:
        queue:           The asyncio.Queue to read events from.
        send_fn:         An async callable that sends one event dict.
        check_connected: Optional sync callable returning False to break the loop.
    """
    try:
        while True:
            event = await queue.get()
            if check_connected is not None and not check_connected():
                break
            await send_fn(event)
    except asyncio.CancelledError:
        pass


async def stop_forward_task(task: Optional[asyncio.Task]) -> None:
    """Cancel a forwarding task and wait for it to finish.

    Safe to call with ``None`` (no-op).  Suppresses ``CancelledError`` raised
    during the await so callers don't need their own try/except.
    """
    if task is None:
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def detach_and_stop(
    run_id: str,
    queue: Optional[asyncio.Queue],
    forward_task: Optional[asyncio.Task],
    manager: Any,
) -> None:
    """Detach a subscriber queue from a run/chat manager and stop the forward task.

    Combines the two-step "detach queue + cancel forward task" cleanup that
    both websocket.py and workflow_ws.py perform on session switch, disconnect,
    and cancel.

    Args:
        run_id:       The session or run ID to detach from.
        queue:        The subscriber queue (may be None if not attached).
        forward_task: The asyncio.Task running forward_events (may be None).
        manager:      Any object with a ``detach(run_id, queue)`` method
                      (e.g. ChatRunManager or WorkflowRunManager).
    """
    if queue is not None:
        manager.detach(run_id, queue)
    await stop_forward_task(forward_task)
