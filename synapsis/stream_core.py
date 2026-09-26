"""Shared streaming utilities for Chat and Workflow paths.

Contains:
- handle_stream_error: shared error handler (Phase 1)
- Shared block handlers for DRY stream processing (Phase 5):
  handle_text_block, handle_thinking_block, handle_tool_use_block,
  handle_tool_result_block
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synapsis.config import logger
from synapsis.constants import (
    CLI_RECONNECT_FAILED_ERROR,
    CONTEXT_WINDOW_ERROR,
    GENERIC_TURN_ERROR,
    PROVIDER_AUTH_ERROR,
    PROVIDER_BUSY_ERROR,
    REFUSAL_NO_FALLBACK_ERROR,
    is_aup_error,
)

if TYPE_CHECKING:
    from synapsis.stream_callbacks import StreamCallbacks


_CONTEXT_MARKERS = (
    "prompt is too long",
    "prompt_too_long",
    "context_length_exceeded",
    "context window",
    "maximum context length",
)
_BUSY_MARKERS = (
    "rate_limit", "rate limit", "overloaded", "too many requests",
    "error code: 429", "error code: 529", "status code 429", "status code 529",
)
_AUTH_MARKERS = ("invalid x-api-key", "authentication_error", "invalid api key", "authentication_failed")


def classify_error(error: BaseException) -> tuple[str, str]:
    """Map an exception from a streaming turn to (code, user-facing message).

    Classification is by SDK error *type* first, then by specific provider
    phrases -- never by loose keywords (L3-13: any text containing "token"
    or "maximum", e.g. a 429 "input tokens per minute", used to be reported
    as "context window limit reached"). The raw text is only logged.
    """
    try:
        from claude_agent_sdk._errors import CLIConnectionError
    except Exception:  # pragma: no cover
        CLIConnectionError = ()  # type: ignore[assignment]

    if CLIConnectionError and isinstance(error, CLIConnectionError):
        return "cli_disconnected", CLI_RECONNECT_FAILED_ERROR
    text = str(error).lower()
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 529) or any(m in text for m in _BUSY_MARKERS):
        return "provider_busy", PROVIDER_BUSY_ERROR
    if any(m in text for m in _CONTEXT_MARKERS):
        return "context_window", CONTEXT_WINDOW_ERROR
    if status == 401 or any(m in text for m in _AUTH_MARKERS):
        return "provider_auth", PROVIDER_AUTH_ERROR
    return "internal", GENERIC_TURN_ERROR


async def send_refusal(send, detail: str = "") -> None:
    """Tell the user the model refused; offer a retry only if their role has
    a fallback model (non-admins by default do not -> plain message)."""
    from synapsis.runtime_policy import fallback_model_for_role

    fallback = fallback_model_for_role()
    if fallback:
        await send({
            "type": "aup_error",
            "message": (detail or REFUSAL_NO_FALLBACK_ERROR)[:500],
            "fallback_model": fallback,
        })
    else:
        await send({"type": "error", "code": "refusal", "message": REFUSAL_NO_FALLBACK_ERROR})


async def handle_stream_error(
    error: Exception,
    send,
    context_label: str = "chat",
) -> None:
    """Shared error handler for stream exceptions.

    Logs the full exception, then sends ONE friendly English ``error`` frame
    (with a ``code``) -- plus an ``aup_error`` frame when the error text is a
    genuine usage-policy refusal and the caller's role has a fallback model.
    """
    logger.exception("Error in %s stream", context_label)
    raw = str(error)
    if is_aup_error(raw):
        await send_refusal(send, raw)
        return
    code, message = classify_error(error)
    await send({"type": "error", "code": code, "message": message})


# ---------------------------------------------------------------------------
# Shared block handlers (Phase 5 — DRY refactor)
# ---------------------------------------------------------------------------

async def handle_text_block(block, callbacks: "StreamCallbacks", already_streamed: bool):
    """Handle a TextBlock from an AssistantMessage.

    Args:
        block: The TextBlock from the Claude SDK.
        callbacks: StreamCallbacks for persistence and transport.
        already_streamed: Whether text was already sent via StreamEvent deltas.
    """
    if not already_streamed:
        await callbacks.emit({"type": "text", "content": block.text})

    await callbacks.persist_message("text", {"content": block.text})

    if callbacks.on_text_complete:
        callbacks.on_text_complete(block.text)


async def handle_thinking_block(block, callbacks: "StreamCallbacks", already_streamed: bool):
    """Handle a ThinkingBlock from an AssistantMessage."""
    if not already_streamed:
        await callbacks.emit({"type": "thinking", "content": block.thinking})

    await callbacks.persist_message("thinking", {"content": block.thinking})


async def handle_tool_use_block(block, callbacks: "StreamCallbacks"):
    """Handle a ToolUseBlock from an AssistantMessage.

    Also emits agent_activity events when the Task tool is used.
    """
    tool_input = block.input
    if hasattr(tool_input, 'model_dump'):
        tool_input = tool_input.model_dump()
    elif hasattr(tool_input, 'dict'):
        tool_input = tool_input.dict()

    msg_data = {
        "type": "tool_use",
        "tool": block.name,
        "input": tool_input,
        "tool_use_id": block.id,
    }
    await callbacks.emit(msg_data)
    await callbacks.persist_message("tool_use", {
        "tool": block.name,
        "input": tool_input,
        "tool_use_id": block.id,
    })

    # Emit agent_activity when Task tool is invoked (orchestrator delegation)
    if block.name == "Task":
        agent_name = ""
        if isinstance(block.input, dict):
            agent_name = block.input.get("agent", block.input.get("description", ""))
        await callbacks.emit({
            "type": "agent_activity",
            "agent": agent_name,
            "status": "started",
            "tool_use_id": block.id,
        })


async def handle_tool_result_block(block, callbacks: "StreamCallbacks", max_length: int = 8000):
    """Handle a ToolResultBlock from an AssistantMessage."""
    content = ""
    if hasattr(block, 'content'):
        if isinstance(block.content, str):
            content = block.content
        elif isinstance(block.content, list):
            parts = []
            for part in block.content:
                if hasattr(part, 'text'):
                    parts.append(part.text)
                elif hasattr(part, 'data'):
                    parts.append(f"[{getattr(part, 'type', 'binary')} data]")
                else:
                    parts.append(str(part))
            content = "\n".join(parts)
        else:
            content = str(block.content)

    is_error = getattr(block, 'is_error', False)
    content_truncated = content[:max_length]

    tool_use_id = getattr(block, 'tool_use_id', '') or ''
    if not tool_use_id:
        logger.warning(
            "ToolResultBlock is missing tool_use_id; "
            "downstream matching may fail (is_error=%s, content length=%d)",
            is_error, len(content_truncated),
        )

    msg_data = {
        "type": "tool_result",
        "content": content_truncated,
        "tool_use_id": tool_use_id,
        "is_error": is_error,
    }
    await callbacks.emit(msg_data)
    await callbacks.persist_message("tool_result", {
        "content": content_truncated,
        "tool_use_id": tool_use_id,
        "is_error": is_error,
    })
