"""Shared utilities for run manager attach/detach/cancel patterns.

Used by ChatRunManager and WorkflowRunManager to avoid duplicating the
cancel-task-and-wait and subscriber-management boilerplate.
"""

import asyncio
from typing import Any


async def cancel_run_task(
    task: asyncio.Task | None,
    cancel_event: asyncio.Event,
    timeout: float = 10.0,
    logger: Any = None,
    label: str = "task",
) -> str | None:
    """Cancel a managed task gracefully: set event, cancel, wait with timeout.

    Returns the resulting status string ("cancelled") only when this function
    had to force-set it (i.e. the task didn't finish in time).  Returns None
    when the task's own finally block already handled the status update.
    """
    cancel_event.set()

    if task is not None and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            if logger:
                logger.warning("%s did not finish within %ss", label, timeout)
            return "cancelled"
        except asyncio.CancelledError:
            pass
        return None
    else:
        # Task already done or absent -- caller should mark cancelled
        return "cancelled"


def attach_subscriber(
    subscribers: list[asyncio.Queue],
    buffer: list[Any],
    maxsize: int = 0,
) -> tuple[list[Any], asyncio.Queue]:
    """Attach a new subscriber queue and return (buffer_copy, queue).

    Args:
        subscribers: The handle's subscriber list to append to.
        buffer: The handle's event buffer to snapshot.
        maxsize: Optional max size for the new asyncio.Queue.

    Returns:
        A tuple of (shallow copy of buffer, new subscriber queue).
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    subscribers.append(queue)
    return list(buffer), queue


def detach_subscriber(
    subscribers: list[asyncio.Queue],
    queue: asyncio.Queue,
) -> None:
    """Remove a subscriber queue from the list (no-op if not present)."""
    try:
        subscribers.remove(queue)
    except ValueError:
        pass
