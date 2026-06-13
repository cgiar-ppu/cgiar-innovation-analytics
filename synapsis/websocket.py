"""
WebSocket chat endpoint -- entry point for /ws/chat.

Architecture overview
---------------------
This module is intentionally thin. Its only job is to accept connections,
parse incoming JSON frames, and route each message type to the appropriate
handler in handlers/chat_handlers.py:

  handlers/chat_handlers.py  -- per-message-type handler functions
  session_manager.py         -- session lifecycle (create, switch, resume, cancel)
  stream_handler.py          -- async streaming of SDK responses (runs as a Task)
  message_handlers.py        -- per-block processing and DB persistence

Public API (imported by server.py):
  ws_chat()              -- the WebSocket endpoint handler
  get_activity_stats()   -- connection/activity snapshot for health endpoints
  cleanup_session_client() -- graceful SDK client teardown on session delete
"""

import asyncio
import json
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from claude_agent_sdk._errors import CLIConnectionError

from synapsis.config import logger
from synapsis.chat_run_manager import chat_run_manager
from synapsis.ws_utils import forward_events, stop_forward_task
from synapsis.session_manager import (
    get_activity_stats,           # re-exported for server.py
    cleanup_session_client,       # re-exported for server.py
    cleanup_orphaned_sessions,
    increment_connections,
    decrement_connections,
    record_activity,
    register_connection,
    unregister_connection,
)
from synapsis.handlers.chat_handlers import (
    handle_cancel,
    handle_switch_session,
    handle_new_session,
    handle_retry,
    handle_switch_model,
    handle_user_message,
)


# ---------------------------------------------------------------------------
# Re-export symbols consumed by server.py
# ---------------------------------------------------------------------------

__all__ = ["ws_chat", "get_activity_stats", "cleanup_session_client"]


# ---------------------------------------------------------------------------
# Main WebSocket handler
# ---------------------------------------------------------------------------

async def ws_chat(websocket: WebSocket) -> None:
    """Main WebSocket handler for /ws/chat.

    Protocol -- client sends JSON frames:
      {"message": "..."}                     -- user chat message
      {"type": "cancel"}                     -- abort in-flight response
      {"type": "new_session"}                -- start a fresh session
      {"type": "switch_session",
       "session_id": "<sid>"}                -- switch to / resume an existing session
      {"type": "switch_model",
       "model": "..."}                       -- switch the active session's model
      {"type": "retry_with_model",
       "message": "...", "model": "..."}     -- retry with AUP fallback model

    Protocol -- server streams JSON frames:
      {"type": "text",        "content": "..."}
      {"type": "thinking",    "content": "..."}
      {"type": "tool_use",    "tool": "...", "input": {...}, "tool_use_id": "..."}
      {"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": bool}
      {"type": "system",      "subtype": "...", "data": "..."}
      {"type": "result",      "estimated_cost": float, "turns": int, ...}
      {"type": "session",     "session_id": "..."}
      {"type": "cancelled"}
      {"type": "error",       "message": "..."}

    Every outgoing frame carries a "session_id" field so the frontend can
    route it to the correct conversation panel.
    """
    await websocket.accept()
    await increment_connections()

    # Per-connection state
    session_id: Optional[str] = None
    client = None

    # Per-connection subscriber tracking for ChatRunManager
    attached_sessions: dict[str, asyncio.Queue] = {}
    forward_tasks: dict[str, asyncio.Task] = {}

    # --- Helper: send a JSON frame tagged with the active session ID ---
    async def send_json(data: dict, *, sid: Optional[str] = None):
        if websocket.client_state == WebSocketState.CONNECTED:
            await record_activity(time.time())
            data["session_id"] = sid or session_id
            try:
                await websocket.send_json(data)
            except RuntimeError:
                # WebSocket closed between the state check and the actual send
                pass

    # --- Helper: attach to a session's ChatRunManager and forward events ---
    async def attach_to_session(sid: str):
        """Attach this connection as a subscriber to a running chat task."""
        # Detach from any previous attachment for this session
        await detach_from_session(sid)
        result = chat_run_manager.attach(sid)
        if result is None:
            return
        buffered_events, queue = result
        attached_sessions[sid] = queue
        # Send buffer replay marker
        await send_json(
            {"type": "buffer_replay_start", "session_id": sid, "event_count": len(buffered_events)},
            sid=sid,
        )
        for event in buffered_events:
            await send_json(event, sid=sid)
        await send_json({"type": "buffer_replay_end", "session_id": sid}, sid=sid)

        # Start forwarding live events using the shared utility
        async def _send_with_sid(event):
            await send_json(event, sid=sid)

        forward_tasks[sid] = asyncio.create_task(
            forward_events(queue, _send_with_sid)
        )

    async def detach_from_session(sid: str):
        """Detach this connection from a session's chat task."""
        queue = attached_sessions.pop(sid, None)
        if queue:
            chat_run_manager.detach(sid, queue)
        await stop_forward_task(forward_tasks.pop(sid, None))

    # Register this connection for global broadcasts now that send_json is defined
    register_connection(send_json)

    try:
        while True:
            raw = await websocket.receive_text()

            # --- Parse incoming frame ---
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Received invalid JSON over WebSocket: %s", exc)
                await send_json(
                    {"type": "error", "message": f"Invalid JSON: {exc}"},
                    sid=session_id,
                )
                continue

            msg_type = payload.get("type", "message")

            # --- Cancel in-flight response ---
            if msg_type == "cancel":
                client = await handle_cancel(
                    payload, session_id, client, send_json
                )
                continue

            # --- Switch to / resume a different session ---
            if msg_type == "switch_session":
                old_sid = session_id
                session_id, client, needs_attach = await handle_switch_session(
                    payload, session_id, send_json
                )
                # Detach from the old session's managed task if we switched to a different one
                if old_sid and old_sid != session_id:
                    await detach_from_session(old_sid)
                if needs_attach and session_id:
                    await attach_to_session(session_id)
                continue

            # --- Create a brand-new session ---
            if msg_type == "new_session":
                session_id, client = await handle_new_session(
                    session_id, send_json
                )
                continue

            # --- Switch the active session's model mid-conversation ---
            if msg_type == "switch_model":
                result = await handle_switch_model(
                    payload, session_id, send_json
                )
                if result is not None:
                    client = result
                continue

            # ----------------------------------------------------------
            # All remaining message types (retry_with_model, regular
            # user message) are wrapped in per-message error handling so
            # a single SDK failure does not kill the WebSocket connection.
            # ----------------------------------------------------------
            try:
                if msg_type == "retry_with_model":
                    result = await handle_retry(
                        payload, session_id, send_json
                    )
                    if result is not None:
                        client = result
                    # Attach to the newly started task so we receive events
                    if session_id:
                        await attach_to_session(session_id)
                    continue

                # --- Regular user message ---
                session_id, client = await handle_user_message(
                    payload, session_id, send_json
                )
                # Attach to the newly started task so we receive events
                if session_id:
                    await attach_to_session(session_id)

            except ValueError:
                # Empty message -- skip silently (handle_user_message raises ValueError)
                continue
            except CLIConnectionError as cli_err:
                # The SDK subprocess died — the auto-recovery in launch_streaming_task
                # already tried to recreate the client.  If we still reach here, show
                # a user-friendly message instead of the raw SDK traceback.
                logger.warning(
                    "CLIConnectionError surfaced to WebSocket handler (session %s): %s",
                    session_id, cli_err,
                )
                await send_json(
                    {
                        "type": "error",
                        "message": (
                            "La sesión se desconectó y no se pudo reconectar automáticamente. "
                            "Por favor, recarga la página para continuar. Tu historial de conversación se conserva."
                        ),
                    },
                    sid=session_id,
                )
            except Exception as msg_err:
                logger.exception("Error handling message (session %s)", session_id)
                await send_json(
                    {"type": "error", "message": str(msg_err)},
                    sid=session_id,
                )

    except WebSocketDisconnect:
        logger.info("Client disconnected (session %s)", session_id)

    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await send_json({"type": "error", "message": str(e)}, sid=session_id)
        except (RuntimeError, ConnectionError):
            pass  # WebSocket may already be closed

    finally:
        await decrement_connections()
        unregister_connection(send_json)

        # Detach from all managed chat tasks (tasks continue in background)
        for sid in list(attached_sessions.keys()):
            await detach_from_session(sid)

        # Clean up sessions that no longer have any WebSocket connections
        # viewing them and are not busy — prevents orphaned CLI subprocesses.
        try:
            await cleanup_orphaned_sessions()
        except Exception:
            logger.debug("Error during orphaned session cleanup", exc_info=True)
