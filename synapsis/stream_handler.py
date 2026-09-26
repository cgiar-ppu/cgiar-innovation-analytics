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

import synapsis.config as _config
from synapsis.config import logger
from synapsis.constants import (
    CONTEXT_WINDOW_ERROR,
    MAX_TURNS_ERROR,
    PROVIDER_BUSY_ERROR,
    STALL_ERROR,
    STREAM_ENDED_EARLY_ERROR,
    TURN_BUDGET_ERROR,
    is_aup_error,
    is_refusal_stop,
)
from synapsis.chat_run_manager import chat_run_manager
from synapsis.stream_core import handle_stream_error, send_refusal
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

    # Set when the stall watchdog stopped the turn
    stalled = False

    stall_timeout = _config.STALL_TIMEOUT_SECONDS

    try:
        stream = client.receive_response().__aiter__()
        while True:
            # --- Stall watchdog: no SDK event for STALL_TIMEOUT seconds ---
            try:
                if stall_timeout and stall_timeout > 0:
                    message = await asyncio.wait_for(stream.__anext__(), timeout=stall_timeout)
                else:
                    message = await stream.__anext__()
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                stalled = True
                await _handle_stall(session_id, client, send_event, stall_timeout)
                break

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
                await _account_result(message, session_id, client)
                # Friendly explanation for limits/errors, and refusal handling
                # based on the SDK's stop reason -- no longer a substring scan
                # of the answer text (L3-13: "aup"/"violate" in normal answers
                # triggered a bogus policy-violation prompt).
                await _explain_result(message, session_id, client, send_event)

        # If the generator ended without a ResultMessage and the user did not
        # cancel, the CLI stopped mid-answer (crash, OOM, killed). Say so
        # plainly instead of claiming the conversation is too long (L3-13).
        if not got_result and not stalled and not (cancel_event and cancel_event.is_set()):
            logger.warning(
                "stream_response ended without ResultMessage (session %s)", session_id
            )
            await send_event({
                "type": "error",
                "code": "stream_ended",
                "message": STREAM_ENDED_EARLY_ERROR,
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
        if not (cancel_event and cancel_event.is_set()) and not stalled:
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
                            await _account_result(leftover, session_id, client)
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
# Runtime accounting, limits and watchdog (Lane D, 2026-09-26)
# ---------------------------------------------------------------------------

def _client_model(client) -> str:
    model = getattr(client, "_ia_model", None)
    if not model:
        model = getattr(getattr(client, "options", None), "model", None)
    return str(model or _config.MODEL)


async def _account_result(message: ResultMessage, session_id: str, client) -> None:
    """Record this question's cost in the usage ledger and decide whether
    the CLI process must be recycled before the next question.

    ``total_cost_usd`` is the running total of the Claude conversation, so
    the question's cost is the difference to the previous total kept on the
    client (see ``session.client_registry.tag_client``).
    """
    from synapsis.database.usage import record_turn_usage, turn_cost_from_totals
    from synapsis.runtime_policy import current_role, current_user_id

    total = message.total_cost_usd
    baseline = getattr(client, "_ia_cost_baseline", 0.0) or 0.0
    cost = turn_cost_from_totals(total, baseline)
    try:
        if total is not None:
            client._ia_cost_baseline = float(total)
        client._ia_spent = float(getattr(client, "_ia_spent", 0.0) or 0.0) + cost
        budget = getattr(client, "_ia_budget", None)
        # The CLI's max_budget_usd counts spend since the process started;
        # replace the process once less than (1 - fraction) x ceiling is left
        # so the next question gets (nearly) the full per-question ceiling.
        if message.subtype == "error_max_budget_usd" or (
            budget and client._ia_spent > budget * _config.BUDGET_RECYCLE_FRACTION
        ):
            client._ia_recycle = True
    except Exception:
        logger.debug("Could not update client accounting for %s", session_id, exc_info=True)

    await record_turn_usage(
        user_id=current_user_id(),
        role=current_role(),
        session_id=session_id,
        model=_client_model(client),
        turn_cost_usd=cost,
        cumulative_cost_usd=float(total) if total is not None else None,
        num_turns=message.num_turns,
        duration_ms=message.duration_ms,
        is_error=bool(message.is_error),
        subtype=message.subtype,
        source="chat",
    )


async def _explain_result(message: ResultMessage, session_id: str, client, send_event) -> None:
    """Send one friendly English frame for a turn that ended on a limit or a
    provider error (the ``result`` frame itself stays unchanged)."""
    send = lambda payload: send_event(payload, sid=session_id)  # noqa: E731
    subtype = message.subtype or ""
    if subtype == "error_max_budget_usd":
        from synapsis.runtime_policy import turn_budget_usd
        limit = getattr(client, "_ia_budget", None) or turn_budget_usd() or 0.0
        await send({"type": "error", "code": "turn_budget", "message": TURN_BUDGET_ERROR.format(limit=limit)})
        return
    if subtype == "error_max_turns":
        await send({"type": "error", "code": "max_turns", "message": MAX_TURNS_ERROR.format(limit=_config.MAX_TURNS)})
        return
    if is_refusal_stop(message.stop_reason):
        await send_refusal(send)
        return
    if not message.is_error:
        return
    errors = " ".join(str(e) for e in (getattr(message, "errors", None) or []))
    if is_aup_error(errors):
        await send_refusal(send, errors)
    elif getattr(message, "terminal_reason", None) == "prompt_too_long":
        await send({"type": "error", "code": "context_window", "message": CONTEXT_WINDOW_ERROR})
    elif getattr(message, "api_error_status", None) in (429, 529):
        await send({"type": "error", "code": "provider_busy", "message": PROVIDER_BUSY_ERROR})


async def _handle_stall(session_id: str, client, send_event, timeout: int) -> None:
    """Stop a turn that produced no SDK event for ``timeout`` seconds."""
    logger.warning("Stall watchdog: no SDK event for %ss in session %s — stopping the turn", timeout, session_id)
    try:
        client._ia_recycle = True
    except Exception:
        pass
    try:
        await asyncio.wait_for(client.interrupt(), timeout=5.0)
    except Exception:
        logger.debug("Interrupt after stall failed for %s", session_id, exc_info=True)
    minutes = max(1, round(timeout / 60))
    duration = "1 minute" if minutes == 1 else f"{minutes} minutes"
    await send_event({
        "type": "error",
        "code": "stalled",
        "message": STALL_ERROR.format(duration=duration),
    }, sid=session_id)


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
