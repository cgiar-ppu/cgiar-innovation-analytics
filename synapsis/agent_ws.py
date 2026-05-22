"""
Per-agent WebSocket endpoint — streaming conversations with a specific agent.

- WS /ws/agent/{agent_id} — Connect to a specific agent for streaming,
  multi-turn conversations. Bypasses the orchestrator.

Protocol — client sends JSON frames:
  {"message": "..."}                     — user message
  {"message": "...", "extra_instructions": "..."}  — with extra context
  {"type": "cancel"}                     — abort in-flight response

Protocol — server sends JSON frames:
  {"type": "agent_info",  "agent_id": "...", "agent_name": "..."}
  {"type": "text",        "content": "..."}          (streaming deltas + complete blocks)
  {"type": "thinking",    "content": "..."}          (thinking deltas + complete blocks)
  {"type": "tool_generating", "tool": "...", "tool_use_id": "..."}  (early tool indicator)
  {"type": "tool_use",    "tool": "...", "input": {...}, "tool_use_id": "..."}
  {"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": bool}
  {"type": "result",      "estimated_cost": float, "turns": int, ...}
  {"type": "error",       "message": "..."}
  {"type": "cancelled"}

Streaming model: StreamEvent deltas are forwarded as they arrive for low latency.
Complete AssistantMessage blocks are then processed; text/thinking blocks are
suppressed if deltas were already streamed (to avoid duplication). This matches
the proven pattern in stream_handler.py and workflow_stream_handler.py.
"""

import asyncio
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from claude_agent_sdk import (
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
)
from claude_agent_sdk.types import StreamEvent
from synapsis.config import logger
from synapsis.services.workflow_step_helpers import resolve_step_agent, build_step_options
from synapsis.session.client_factory import create_client_with_retry


async def ws_agent(websocket: WebSocket, agent_id: str) -> None:
    """WebSocket handler for /ws/agent/{agent_id}.

    Provides streaming, multi-turn conversations with a specific agent.
    Each WebSocket connection gets its own dedicated agent client.
    """
    await websocket.accept()

    # --- Resolve the agent ---
    is_orchestrator, agent_def, agent_name = await resolve_step_agent(agent_id)

    if not is_orchestrator and not agent_def:
        await websocket.send_json({
            "type": "error",
            "message": f"Agent '{agent_id}' not found. Use GET /api/agents to list available agents.",
        })
        await websocket.close()
        return

    # Send agent info to client
    await websocket.send_json({
        "type": "agent_info",
        "agent_id": agent_id,
        "agent_name": agent_name,
    })

    # Build agent-specific options
    base_opts = await build_step_options(is_orchestrator, agent_id, agent_def, {})
    client: Optional[ClaudeSDKClient] = None
    current_task: Optional[asyncio.Task] = None

    async def send_json(data: dict):
        """Send a JSON frame if the connection is still open."""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json(data)
            except RuntimeError:
                pass

    async def stream_response(prompt: str, extra_instructions: str = ""):
        """Stream the agent's response to the WebSocket.

        Follows the same streaming pattern as stream_handler.py:
        1. StreamEvent deltas are forwarded immediately for low latency
        2. Complete AssistantMessage blocks are processed for tool_use/tool_result
        3. Text/thinking blocks are suppressed if already streamed via deltas
        """
        nonlocal client

        # Apply extra instructions if provided
        if extra_instructions:
            current_opts = await build_step_options(
                is_orchestrator, agent_id, agent_def,
                {"extra_instructions": extra_instructions},
            )
        else:
            current_opts = base_opts

        # Track whether deltas were already streamed (avoid duplication)
        streamed_text = False
        streamed_thinking = False

        try:
            # Create a fresh client for each turn
            client = await create_client_with_retry(current_opts)
            await client.query(prompt)

            async for message in client.receive_response():

                # --- StreamEvent: partial deltas (lowest latency path) ---
                # This matches the proven pattern in stream_handler.py
                if isinstance(message, StreamEvent):
                    event = message.event
                    event_type = event.get("type", "")

                    # Forward early tool indicator on content_block_start
                    if event_type == "content_block_start":
                        content_block = event.get("content_block", {})
                        if content_block.get("type") == "tool_use":
                            tool_name = content_block.get("name", "")
                            if tool_name:
                                await send_json({
                                    "type": "tool_generating",
                                    "tool": tool_name,
                                    "tool_use_id": content_block.get("id", ""),
                                })
                        continue

                    if event_type != "content_block_delta":
                        continue

                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")

                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            await send_json({"type": "text", "content": text})
                            streamed_text = True

                    elif delta_type == "thinking_delta":
                        thinking = delta.get("thinking", "")
                        if thinking:
                            await send_json({"type": "thinking", "content": thinking})
                            streamed_thinking = True

                    elif delta_type == "input_json_delta":
                        json_chunk = delta.get("partial_json", "")
                        if json_chunk:
                            await send_json({
                                "type": "tool_input_delta",
                                "content": json_chunk,
                            })

                # --- AssistantMessage: complete content blocks ---
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            # Only send if not already streamed via deltas
                            if not streamed_text:
                                await send_json({"type": "text", "content": block.text})
                            streamed_text = False  # Reset for next block

                        elif isinstance(block, ThinkingBlock):
                            if not streamed_thinking:
                                await send_json({"type": "thinking", "content": block.thinking})
                            streamed_thinking = False

                        elif isinstance(block, ToolUseBlock):
                            tool_input = block.input
                            if hasattr(tool_input, 'model_dump'):
                                tool_input = tool_input.model_dump()
                            elif hasattr(tool_input, 'dict'):
                                tool_input = tool_input.dict()
                            await send_json({
                                "type": "tool_use",
                                "tool": block.name,
                                "input": tool_input,
                                "tool_use_id": block.id,
                            })

                        elif isinstance(block, ToolResultBlock):
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

                            # Truncate very long tool results
                            content_truncated = content[:8000]
                            await send_json({
                                "type": "tool_result",
                                "tool_use_id": getattr(block, 'tool_use_id', '') or '',
                                "content": content_truncated,
                                "is_error": getattr(block, 'is_error', False),
                            })

                # --- SystemMessage: init handshake, etc. ---
                elif isinstance(message, SystemMessage):
                    # Forward system messages as-is (optional, useful for debugging)
                    if message.subtype == "api_key_source":
                        continue  # Skip noisy auth info
                    data_val = (
                        json.dumps(message.data) if isinstance(message.data, dict)
                        else str(message.data) if message.data is not None
                        else None
                    )
                    await send_json({
                        "type": "system",
                        "subtype": message.subtype,
                        "data": data_val,
                    })

                # --- ResultMessage: end of turn ---
                elif isinstance(message, ResultMessage):
                    await send_json({
                        "type": "result",
                        "estimated_cost": message.total_cost_usd,
                        "turns": message.num_turns,
                        "duration_ms": message.duration_ms,
                        "session_id": message.session_id,
                    })

        except asyncio.CancelledError:
            await send_json({"type": "cancelled"})
        except Exception as exc:
            logger.exception("Agent WS streaming error for %s", agent_id)
            await send_json({"type": "error", "message": str(exc)})

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                await send_json({"type": "error", "message": f"Invalid JSON: {exc}"})
                continue

            msg_type = payload.get("type", "message")

            # Cancel in-flight response
            if msg_type == "cancel":
                if current_task and not current_task.done():
                    current_task.cancel()
                    await send_json({"type": "cancelled"})
                continue

            # Regular user message
            user_msg = payload.get("message", "").strip()
            if not user_msg:
                await send_json({"type": "error", "message": "Empty message"})
                continue

            extra = payload.get("extra_instructions", "")

            # Cancel any previous in-flight task
            if current_task and not current_task.done():
                current_task.cancel()

            # Start streaming in background task
            current_task = asyncio.create_task(
                stream_response(user_msg, extra)
            )

    except WebSocketDisconnect:
        logger.info("Agent WS client disconnected (agent: %s)", agent_id)
    except Exception as e:
        logger.exception("Agent WebSocket error")
        try:
            await send_json({"type": "error", "message": str(e)})
        except (RuntimeError, ConnectionError):
            pass
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
