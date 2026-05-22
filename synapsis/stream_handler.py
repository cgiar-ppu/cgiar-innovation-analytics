"""
Stream handler — consumes the async generator produced by ClaudeSDKClient.

Iterates over every message yielded by client.receive_response(), dispatches
to the appropriate handler in message_handlers.py, accumulates streaming delta
flags, and detects context-window exhaustion. Runs as a background asyncio.Task
so each session can stream independently without blocking the WebSocket reader.
"""

import asyncio
from typing import Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
)
from claude_agent_sdk.types import StreamEvent

from synapsis.config import logger, FALLBACK_MODEL
from synapsis.constants import CONTEXT_WINDOW_ERROR, is_aup_error
from synapsis.chat_run_manager import chat_run_manager
from synapsis.stream_core import handle_stream_error
from synapsis.message_handlers import (
    handle_assistant_block,
    handle_system_message,
    handle_result_message,
)


# ---------------------------------------------------------------------------
# Main streaming coroutine
# ---------------------------------------------------------------------------

async def stream_response(
    session_id: str,
    client: ClaudeSDKClient,
    cancel_event: Optional[asyncio.Event],
    send_event,
    on_complete=None,
) -> None:
    """Stream agent response messages to subscribers via the ChatRunManager.

    Runs as an asyncio.Task managed by the ChatRunManager. Each active session
    gets its own managed task, allowing concurrent streaming across multiple
    sessions.

    The function handles four SDK message types:
    - StreamEvent:       Partial text/thinking deltas (sent immediately for low latency).
    - AssistantMessage:  Complete content blocks (text, thinking, tool_use, tool_result).
    - SystemMessage:     Internal SDK events (session init, api_key_source, etc.).
    - ResultMessage:     Final turn summary with cost, duration, and session UUID.

    Args:
        session_id:      App session ID used to tag outgoing WebSocket messages.
        client:          The connected ClaudeSDKClient for this session.
        cancel_event:    asyncio.Event set when the user cancels the response.
        send_event:      Async callable provided by the ChatRunManager that
                         buffers events and fans out to all subscriber queues.
        on_complete:     Optional zero-argument callback invoked in the finally
                         block before the session_complete frame is sent.
                         Intended for releasing the per-session lock acquired
                         before streaming (see session_manager.release_session_client).
    """
    # Track whether deltas were already streamed so complete blocks are not duplicated
    streamed_text = False
    streamed_thinking = False

    # Set to True once we receive a ResultMessage (marks a clean stream end)
    got_result = False

    # Accumulate all streamed text for AUP/policy error detection
    accumulated_text = ""

    try:
        async for message in client.receive_response():
            # Honour a cancellation request as quickly as possible
            if cancel_event and cancel_event.is_set():
                break

            # --- StreamEvent: partial deltas (lowest latency path) ---
            if isinstance(message, StreamEvent):
                await _handle_stream_event(message, session_id, send_event)
                # Track whether any delta was sent so the complete block handler
                # knows not to re-send the same content
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")
                    if delta_type == "text_delta" and delta.get("text"):
                        streamed_text = True
                        accumulated_text += delta.get("text", "")
                    elif delta_type == "thinking_delta" and delta.get("thinking"):
                        streamed_thinking = True

            # --- AssistantMessage: complete content blocks ---
            elif isinstance(message, AssistantMessage):
                streamed_text, streamed_thinking = await _handle_assistant_message(
                    message, session_id, streamed_text, streamed_thinking,
                    cancel_event, send_event,
                )

            # --- SystemMessage: init handshake, api_key_source, etc. ---
            elif isinstance(message, SystemMessage):
                await handle_system_message(message, session_id, send_event)

            # --- ResultMessage: end of turn ---
            elif isinstance(message, ResultMessage):
                got_result = True
                await handle_result_message(message, session_id, send_event)
                # Check for AUP/policy errors in accumulated text
                if accumulated_text and is_aup_error(accumulated_text):
                    await send_event({
                        "type": "aup_error",
                        "message": accumulated_text[:500],
                        "fallback_model": FALLBACK_MODEL,
                    }, sid=session_id)

        # If the generator ended without a ResultMessage and the user did not
        # cancel, this almost always means the context window was exhausted.
        if not got_result and not (cancel_event and cancel_event.is_set()):
            logger.warning(
                "stream_response ended without ResultMessage (session %s) — "
                "possible context window exhaustion", session_id
            )
            await send_event({
                "type": "error",
                "message": CONTEXT_WINDOW_ERROR,
            }, sid=session_id)

    except asyncio.CancelledError:
        # Task was cancelled programmatically (cancel button or disconnect)
        logger.info("Response streaming cancelled (session %s)", session_id)
        raise  # Let run_task see the cancellation for correct status tracking

    except Exception as e:
        await handle_stream_error(
            e,
            send=lambda payload: send_event(payload, sid=session_id),
            context_label="chat",
        )

    finally:
        # ------------------------------------------------------------------
        # Drain any background SDK messages that arrived after the turn ended.
        #
        # When a `run_in_background` bash command (or similar async SDK task)
        # completes between turns, the SDK queues a notification internally.
        # Without this drain, those messages stay trapped until the user sends
        # the next query — at which point they surface mixed in with the new
        # response, appearing out of context.
        #
        # We give the SDK 1.0 s to yield any already-queued messages.  If it
        # blocks (nothing queued) the timeout fires and we move on.  Only
        # SystemMessage payloads are forwarded; any other type signals the
        # start of a new turn's content and we stop immediately.
        # ------------------------------------------------------------------
        if not (cancel_event and cancel_event.is_set()):
            try:
                async def _drain_queued() -> None:
                    async for leftover in client.receive_response():
                        if isinstance(leftover, SystemMessage):
                            # Log task_notification subtypes specifically so we
                            # can diagnose background-task drain behaviour in
                            # production logs without raising the overall level.
                            if getattr(leftover, 'subtype', '') == 'task_notification':
                                logger.debug(
                                    "Drain: caught background task_notification for session %s",
                                    session_id,
                                )
                            await handle_system_message(leftover, session_id, send_event)
                        elif isinstance(leftover, ResultMessage):
                            # A background task produced a result — persist the
                            # session UUID via the standard handler then stop.
                            await handle_result_message(leftover, session_id, send_event)
                            break
                        else:
                            # Unexpected message type — do not consume it.
                            break

                # 1.0 s gives background task_notification messages more time to
                # arrive than the previous 0.5 s window.  Notifications that still
                # miss this window are caught by the pre-drain in chat_handlers.py.
                await asyncio.wait_for(_drain_queued(), timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass  # Expected: nothing queued or task was cancelled
            except Exception as _drain_err:
                # Non-critical — log at debug level and continue cleanup
                logger.debug(
                    "Background message drain ended for session %s: %s",
                    session_id, _drain_err,
                )

        # Release the per-session lock (if the caller supplied a callback).
        # This must happen before sending session_complete so the lock is free
        # by the time a second connection receives the completion signal.
        if on_complete:
            on_complete()
        # Notify frontend this session's streaming task has finished.
        # Use the guard flag to ensure session_complete is only emitted once
        # per run — _broadcast_session_complete (fired by on_complete above)
        # also sends session_complete, and without this guard subscribers
        # would receive it twice.
        handle = chat_run_manager.get_handle(session_id)
        current_run_id = handle.run_id if handle else None
        if chat_run_manager.try_mark_session_complete(session_id, run_id=current_run_id):
            try:
                await send_event({"type": "session_complete", "session_id": session_id}, sid=session_id)
            except (RuntimeError, ConnectionError):
                pass  # WebSocket may already be closed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _handle_stream_event(
    message: StreamEvent,
    session_id: str,
    send_json,
) -> None:
    """Forward text and thinking deltas to the WebSocket as they arrive.

    Only content_block_delta events carry partial content; all other event
    types (e.g. message_start, content_block_start) are silently ignored
    because they carry no user-visible data.
    """
    event = message.event
    event_type = event.get("type", "")

    # Forward content_block_start for tool_use blocks so the frontend can
    # show an early "Preparing [tool_name]..." indicator before the complete
    # tool_use block arrives.
    if event_type == "content_block_start":
        content_block = event.get("content_block", {})
        if content_block.get("type") == "tool_use":
            tool_name = content_block.get("name", "")
            if tool_name:
                await send_json({
                    "type": "tool_generating",
                    "tool": tool_name,
                    "tool_use_id": content_block.get("id", ""),
                }, sid=session_id)
        return

    if event_type != "content_block_delta":
        return

    delta = event.get("delta", {})
    delta_type = delta.get("type", "")

    if delta_type == "text_delta":
        text = delta.get("text", "")
        if text:
            await send_json({"type": "text", "content": text}, sid=session_id)

    elif delta_type == "thinking_delta":
        thinking = delta.get("thinking", "")
        if thinking:
            await send_json({"type": "thinking", "content": thinking}, sid=session_id)

    elif delta_type == "input_json_delta":
        # Stream tool input as it's being generated so the frontend can
        # show real-time tool input construction.
        json_chunk = delta.get("partial_json", "")
        if json_chunk:
            await send_json({
                "type": "tool_input_delta",
                "content": json_chunk,
            }, sid=session_id)


async def _handle_assistant_message(
    message: AssistantMessage,
    session_id: str,
    streamed_text: bool,
    streamed_thinking: bool,
    cancel_event: Optional[asyncio.Event],
    send_json,
) -> tuple[bool, bool]:
    """Process all blocks in a complete AssistantMessage.

    Iterates each content block and delegates to handle_assistant_block().
    Resets the streamed_text / streamed_thinking flags after processing each
    matching block type so subsequent blocks in the same message are handled
    correctly.

    Returns:
        Updated (streamed_text, streamed_thinking) tuple.
    """
    for block in message.content:
        # Respect cancellation between blocks to avoid extra work
        if cancel_event and cancel_event.is_set():
            break

        await handle_assistant_block(
            block, session_id, streamed_text, streamed_thinking, send_json
        )

        # Reset flags after the corresponding complete block is processed
        if isinstance(block, TextBlock):
            streamed_text = False
        elif isinstance(block, ThinkingBlock):
            streamed_thinking = False

    return streamed_text, streamed_thinking
