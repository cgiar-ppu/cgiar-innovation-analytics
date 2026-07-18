"""
Message handlers — process individual message blocks and SDK message types.

Contains the per-block assistant handler and the SystemMessage / ResultMessage
handlers extracted from websocket.py. Also owns the serialization helpers used
when persisting messages to the database. Imported by stream_handler.py.
"""

import json
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from synapsis.config import AUTH_METHOD, logger
from synapsis.constants import TOOL_RESULT_MAX_LENGTH
from synapsis.database import save_message, save_claude_session_id
from synapsis.stream_callbacks import StreamCallbacks
from synapsis.stream_core import (
    handle_text_block, handle_thinking_block,
    handle_tool_use_block, handle_tool_result_block,
)

# Track which sessions have already received their first init message.
# Subsequent init messages (triggered by slash commands) are suppressed
# from the frontend chat but still processed for session UUID persistence.
_sessions_initialized: set[str] = set()


# ---------------------------------------------------------------------------
# Chat-specific StreamCallbacks factory
# ---------------------------------------------------------------------------

def create_chat_callbacks(session_id: str, send_json) -> StreamCallbacks:
    """Create StreamCallbacks wired for the Chat path.

    This allows Chat code to use the shared block handlers in stream_core.py
    when desired, while the existing handle_assistant_block / handle_system_message
    / handle_result_message functions remain available for backward compatibility.
    """
    async def _persist(msg_type: str, data: dict):
        await save_message(session_id, msg_type, data)

    async def _send(payload: dict):
        await send_json(payload, sid=session_id)

    async def _persist_sid(claude_sid: str):
        await save_claude_session_id(session_id, claude_sid)

    return StreamCallbacks(
        send=_send,
        persist_message=_persist,
        persist_session_id=_persist_sid,
    )


# ---------------------------------------------------------------------------
# Assistant block handler
# ---------------------------------------------------------------------------

async def handle_assistant_block(
    block,
    session_id: str,
    streamed_text: bool,
    streamed_thinking: bool,
    send_json,
) -> None:
    """Process a single content block from a completed AssistantMessage.

    For text and thinking blocks the content is only sent over the WebSocket if
    streaming deltas were NOT already sent (i.e. streamed_text / streamed_thinking
    is False). The content is always persisted to the database regardless.

    Args:
        block:            One of TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock.
        session_id:       App session ID (for DB persistence and WS tagging).
        streamed_text:    True if text deltas were already streamed for this turn.
        streamed_thinking: True if thinking deltas were already streamed for this turn.
        send_json:        Coroutine for sending a JSON payload to the WebSocket.
    """
    if isinstance(block, TextBlock):
        # Only send full text if it wasn't already delivered as streaming deltas
        if not streamed_text:
            await send_json({"type": "text", "content": block.text}, sid=session_id)
        # Post-process PRMS result-code citations: rewrite bare/bracketed
        # [R<code>] tokens into public-URL markdown links before persisting, so
        # exports and reloaded history carry clickable, public-only citations
        # (July-7 Step 2). Streamed deltas are left untouched; this only affects
        # the persisted copy. Never emits a session-gated PRMS URL.
        from synapsis.tools.result_code_citation import linkify_result_codes
        await save_message(session_id, "text", {"content": linkify_result_codes(block.text)})

    elif isinstance(block, ThinkingBlock):
        # Same streaming-guard logic as text
        if not streamed_thinking:
            await send_json({"type": "thinking", "content": block.thinking}, sid=session_id)
        await save_message(session_id, "thinking", {"content": block.thinking})

    elif isinstance(block, ToolUseBlock):
        msg_data = {
            "type": "tool_use",
            "tool": block.name,
            "input": block.input,
            "tool_use_id": block.id,
        }
        await send_json(msg_data, sid=session_id)
        await save_message(session_id, "tool_use", {
            "tool": block.name,
            "input": block.input,
            "tool_use_id": block.id,
        })
        # Emit agent_activity when Task tool is invoked
        if block.name == "Task":
            agent_name = ""
            if isinstance(block.input, dict):
                agent_name = block.input.get("agent", block.input.get("description", ""))
            await send_json({
                "type": "agent_activity",
                "agent": agent_name,
                "status": "started",
                "tool_use_id": block.id,
            }, sid=session_id)

    elif isinstance(block, ToolResultBlock):
        # Serialize content to string (may arrive as dict or list from the SDK)
        content_str = (
            block.content
            if isinstance(block.content, str)
            else json.dumps(block.content)
        )
        tool_use_id = getattr(block, 'tool_use_id', '') or ''
        if not tool_use_id:
            logger.warning(
                "ToolResultBlock is missing tool_use_id in chat handler "
                "(session=%s, is_error=%s)",
                session_id, block.is_error,
            )
        msg_data = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            # Truncate large results to avoid overloading the frontend/DB
            "content": content_str[:TOOL_RESULT_MAX_LENGTH],
            "is_error": block.is_error or False,
        }
        await send_json(msg_data, sid=session_id)
        await save_message(session_id, "tool_result", {
            "tool_use_id": tool_use_id,
            "content": content_str[:TOOL_RESULT_MAX_LENGTH],
            "is_error": block.is_error or False,
        })


# ---------------------------------------------------------------------------
# System message handler
# ---------------------------------------------------------------------------

async def handle_system_message(
    message: SystemMessage,
    session_id: str,
    send_json,
) -> None:
    """Process a SystemMessage (e.g. session init, api_key_source).

    The "init" subtype carries the Claude SDK session UUID which is persisted
    so the session can be resumed after a disconnect or cancel.

    The "api_key_source" subtype is deliberately suppressed — it is noisy and
    not useful to the frontend.

    Init messages after the first are suppressed from the chat display because
    every slash command triggers a re-initialization that would flood the UI
    with large JSON blobs. The first init is sent as a compact summary; subsequent
    ones are silently processed for UUID persistence only.
    """
    # Persist the Claude session UUID from the init handshake
    if message.subtype == "init" and isinstance(message.data, dict):
        init_csid = message.data.get("session_id", "")
        if init_csid:
            await save_claude_session_id(session_id, init_csid)

        # Only forward the first init to the frontend; suppress subsequent ones
        # (every slash command triggers a re-init that would flood the chat).
        if session_id in _sessions_initialized:
            logger.debug(
                "Suppressing duplicate init message for session %s", session_id
            )
            return
        _sessions_initialized.add(session_id)

        # Send a compact summary instead of the raw JSON blob
        data = message.data
        summary = {
            "model": data.get("model", "unknown"),
            "tools": len(data.get("tools", [])),
            "mcp_servers": [
                {"name": s.get("name"), "status": s.get("status")}
                for s in data.get("mcp_servers", [])
            ],
            "slash_commands": data.get("slash_commands", []),
            "skills": data.get("skills", []),
            "agents": data.get("agents", []),
        }
        await send_json({
            "type": "system",
            "subtype": "init",
            "data": json.dumps(summary),
        }, sid=session_id)
        return

    # Filter out api_key_source — purely internal SDK telemetry
    if message.subtype == "api_key_source":
        return

    # Normalize the data payload to a string for consistent JSON serialization
    data_val = _serialize_message_data(message.data)

    await send_json({
        "type": "system",
        "subtype": message.subtype,
        "data": data_val,
    }, sid=session_id)


# ---------------------------------------------------------------------------
# Result message handler
# ---------------------------------------------------------------------------

async def handle_result_message(
    message: ResultMessage,
    session_id: str,
    send_json,
) -> None:
    """Process a ResultMessage — the final message after every agent turn.

    Persists the Claude SDK session UUID (for future resumption) and sends
    cost/duration metadata to the frontend. Also saves a result record to DB.
    """
    # Keep the session UUID up-to-date (it may change between turns)
    if message.session_id:
        await save_claude_session_id(session_id, message.session_id)

    # Provide a human-readable error string when the agent encountered an error
    error_detail = _extract_error_detail(message)

    # Forward the result text from slash commands (e.g. /config, /usage)
    # that return output solely via ResultMessage.result without streaming.
    result_text = message.result or ""

    # Debug: log all ResultMessage fields for diagnostic purposes
    logger.debug(
        "ResultMessage for session %s: turns=%d, duration_ms=%d, is_error=%s, "
        "result=%r, usage=%r, subtype=%s, stop_reason=%s",
        session_id, message.num_turns, message.duration_ms, message.is_error,
        message.result[:200] if message.result else None,
        message.usage, message.subtype, message.stop_reason,
    )

    msg_data = {
        "type": "result",
        "estimated_cost": message.total_cost_usd,
        "turns": message.num_turns,
        "duration_ms": message.duration_ms,
        "session_id": message.session_id,
        "is_error": message.is_error,
        "error_detail": error_detail,
        "auth_method": AUTH_METHOD,
        "result_text": result_text,
    }
    await send_json(msg_data, sid=session_id)
    await save_message(session_id, "result", {
        "estimated_cost": message.total_cost_usd,
        "turns": message.num_turns,
        "duration_ms": message.duration_ms,
        "is_error": message.is_error,
        "error_detail": error_detail,
        "result_text": result_text,
    })


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_message_data(data) -> Optional[str]:
    """Normalize a message data payload to str | None.

    The SDK can return dicts, strings, or other objects. This helper converts
    everything to a consistent string form for JSON serialization.
    """
    if isinstance(data, dict):
        return json.dumps(data)
    if data is not None and not isinstance(data, str):
        return str(data)
    return data


def _extract_error_detail(message: ResultMessage) -> str:
    """Extract a non-empty error string from a ResultMessage.

    Returns an empty string when the message is not an error. Provides a
    generic fallback if the SDK error attribute is missing or empty.
    """
    if not message.is_error:
        return ""
    detail = getattr(message, "error", "") or ""
    if not detail:
        detail = "The agent encountered an error."
    return detail
