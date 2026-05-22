"""Shared streaming utilities for Chat and Workflow paths.

Contains:
- handle_stream_error: shared error handler (Phase 1)
- Shared block handlers for DRY stream processing (Phase 5):
  handle_text_block, handle_thinking_block, handle_tool_use_block,
  handle_tool_result_block
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synapsis.config import logger, FALLBACK_MODEL
from synapsis.constants import is_aup_error

if TYPE_CHECKING:
    from synapsis.stream_callbacks import StreamCallbacks


async def handle_stream_error(
    error: Exception,
    send,
    context_label: str = "chat",
) -> None:
    """Shared error handler for stream exceptions.

    Detects context-window and AUP errors and sends appropriate
    typed events. Always sends a generic error event as well.
    """
    logger.exception("Error in %s stream", context_label)
    err_msg = str(error)

    # Provide more actionable message for context-length errors
    if any(kw in err_msg.lower() for kw in ("context", "token", "too long", "maximum")):
        err_msg = (
            f"Context window limit reached: {err_msg}. "
            "Please reduce input size or split into smaller steps."
        )

    if is_aup_error(err_msg):
        await send({
            "type": "aup_error",
            "message": err_msg[:500],
            "fallback_model": FALLBACK_MODEL,
        })

    await send({"type": "error", "message": err_msg})


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
