"""
Shared helpers for WebSocket chat message handlers.

Extracted from chat_handlers.py to eliminate repeated patterns.
"""

import asyncio
from typing import Optional

from claude_agent_sdk import SystemMessage
from claude_agent_sdk._errors import CLIConnectionError

from synapsis.config import logger
from synapsis.database import save_message, update_session_task_status
from synapsis.message_handlers import handle_system_message
from synapsis.session_manager import (
    get_session_lock,
    acquire_session_client,
    release_session_client,
    broadcast_to_all,
)
from synapsis.stream_handler import stream_response


# ---------------------------------------------------------------------------
# Pre-drain helper
# ---------------------------------------------------------------------------

async def pre_drain_stale_messages(
    client,
    session_id: str,
    send_json,
    timeout: float = 1.0,
) -> None:
    """Consume stale background task notifications before a new query.

    After a previous turn's drain window closes, stale ``SystemMessage``
    notifications may remain queued in the SDK client's receive buffer.
    If they are not drained before the next ``client.query()``, the agent
    will respond to the stale notification instead of the user's new
    message.

    This helper iterates ``client.receive_response()`` with a short
    timeout, forwarding any ``SystemMessage`` instances to the frontend
    via *send_json* and stopping as soon as a non-system message appears
    (which would indicate a new turn has already started).

    The function silently swallows ``TimeoutError`` and
    ``CancelledError`` (the common case when nothing is queued) and logs
    any other exception at DEBUG level.

    Args:
        client: A connected ``ClaudeSDKClient`` instance.
        session_id: The current session identifier (for logging and
            forwarding).
        send_json: An async callable used to forward messages to the
            WebSocket client.
        timeout: Maximum seconds to wait for stale messages.  Defaults
            to 0.3.
    """
    try:
        async def _drain():
            async for stale_msg in client.receive_response():
                if isinstance(stale_msg, SystemMessage):
                    logger.debug(
                        "Pre-drain: forwarding stale %s for session %s",
                        stale_msg.subtype, session_id,
                    )
                    await handle_system_message(stale_msg, session_id, send_json)
                else:
                    # Consume stale non-system messages (e.g. AssistantMessage from
                    # background tasks) instead of breaking. Log them for diagnostics.
                    logger.debug(
                        "Pre-drain: consumed stale %s for session %s",
                        type(stale_msg).__name__, session_id,
                    )
        await asyncio.wait_for(_drain(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass  # Expected: nothing queued
    except Exception as drain_err:
        logger.debug("Pre-drain ended for session %s: %s", session_id, drain_err)


# ---------------------------------------------------------------------------
# Stream completion helpers
# ---------------------------------------------------------------------------

def on_stream_complete(session_id: str, lock_acquired: bool = True, run_id: str | None = None) -> None:
    """Release the per-session lock and update task status after streaming ends."""
    if lock_acquired:
        release_session_client(session_id)
    asyncio.ensure_future(_update_task_status_idle(session_id))
    asyncio.ensure_future(_broadcast_session_complete(session_id, run_id=run_id))


async def _update_task_status_idle(session_id: str) -> None:
    """Update the session task status to 'idle' in the database."""
    try:
        await update_session_task_status(session_id, "idle")
    except Exception as exc:
        logger.debug("Failed to update task_status to idle for %s: %s", session_id, exc)


async def _broadcast_session_complete(session_id: str, run_id: str | None = None) -> None:
    """Broadcast session_complete to ALL WebSocket connections.

    When a user switches away from a streaming session, the backend detaches
    their connection from the ChatRunManager event stream. If the session
    completes while detached, the ``session_complete`` event is buffered but
    never forwarded. This broadcast ensures every connected client receives
    the completion signal regardless of subscription state.

    Uses the ChatRunManager guard flag to ensure session_complete is only
    emitted once per run. If ``stream_response`` already sent it via the
    subscriber path, this broadcast is skipped to prevent duplicates.
    The run_id parameter prevents cross-turn guard corruption.
    """
    from synapsis.chat_run_manager import chat_run_manager

    if not chat_run_manager.try_mark_session_complete(session_id, run_id=run_id):
        logger.debug(
            "Skipping broadcast session_complete for %s -- already emitted via subscriber path",
            session_id,
        )
        return
    try:
        await broadcast_to_all({
            "type": "session_complete",
            "session_id": session_id,
            "run_id": run_id,
        })
    except Exception as exc:
        logger.debug("Failed to broadcast session_complete for %s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Shared streaming task launcher
# ---------------------------------------------------------------------------

async def launch_streaming_task(
    session_id: Optional[str],
    client,
    sdk_message: str,
    send_json,
    *,
    lock_acquired: bool = False,
) -> None:
    """Pre-drain, query, and start a managed streaming task for a session.

    This encapsulates the shared pattern used by both ``handle_retry`` and
    ``handle_user_message``: pre-drain stale messages, send the query to
    the SDK, create the streaming closure, and register it with the
    ChatRunManager.  On error the session lock is released if it was held.

    Args:
        session_id:     The chat session identifier.
        client:         A connected ``ClaudeSDKClient`` instance.
        sdk_message:    The message string to send to the SDK.
        send_json:      Async callable for forwarding events to the frontend.
        lock_acquired:  Whether the caller already holds the per-session lock.
    """
    from synapsis.chat_run_manager import chat_run_manager
    from synapsis.session_manager import sessions, session_manager as _sm

    try:
        await pre_drain_stale_messages(client, session_id, send_json)
        await client.query(sdk_message)

        async def run_stream(send_event, cancel_event):
            await stream_response(
                session_id,
                client,
                cancel_event,
                send_event,
                on_complete=lambda sid=session_id: on_stream_complete(
                    sid, lock_acquired,
                    run_id=chat_run_manager.get_handle(sid).run_id if chat_run_manager.get_handle(sid) else None,
                ),
            )

        await chat_run_manager.start_task(session_id, run_stream, client=client)

        if session_id:
            await update_session_task_status(session_id, "running")

    except CLIConnectionError as cli_err:
        # The SDK subprocess died (e.g. server restart, idle timeout, crash).
        # Discard the dead client, recreate via resume, and retry the query once.
        logger.warning(
            "CLIConnectionError for session %s: %s — attempting auto-recovery",
            session_id, cli_err,
        )
        if session_id and session_id in sessions:
            del sessions[session_id]
        if lock_acquired and session_id:
            release_session_client(session_id)
            lock_acquired = False

        try:
            client = await _sm._client_registry._resume_or_create_client(session_id, sessions)
            # Re-acquire the lock for the new client
            lock = get_session_lock(session_id)
            await lock.acquire()
            lock_acquired = True

            await client.query(sdk_message)

            async def run_stream_retry(send_event, cancel_event):
                await stream_response(
                    session_id,
                    client,
                    cancel_event,
                    send_event,
                    on_complete=lambda sid=session_id: on_stream_complete(
                        sid, lock_acquired,
                        run_id=chat_run_manager.get_handle(sid).run_id if chat_run_manager.get_handle(sid) else None,
                    ),
                )

            await chat_run_manager.start_task(session_id, run_stream_retry, client=client)

            if session_id:
                await update_session_task_status(session_id, "running")

            logger.info("Auto-recovery succeeded for session %s", session_id)

        except Exception as retry_err:
            logger.error(
                "Auto-recovery failed for session %s: %s", session_id, retry_err,
            )
            if lock_acquired and session_id:
                release_session_client(session_id)
            raise

    except Exception:
        if lock_acquired and session_id:
            release_session_client(session_id)
        raise
    except asyncio.CancelledError:
        # CancelledError is BaseException -- still need to release the lock
        if lock_acquired and session_id:
            release_session_client(session_id)
        raise
