"""Workflow stream handler -- consumes the Claude SDK response stream for a single step.

Split from workflow_executor.py (Phase 3A) to isolate the streaming/block-handling
loop from step-level orchestration and pipeline-level control flow.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Callable, Awaitable, Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from claude_agent_sdk.types import StreamEvent

from synapsis.config import logger, FALLBACK_MODEL
from synapsis.constants import is_aup_error, CONTEXT_WINDOW_ERROR, OUTPUT_TEXT_MAX_LENGTH
from synapsis.stream_core import (
    handle_stream_error,
    handle_text_block, handle_thinking_block,
    handle_tool_use_block, handle_tool_result_block,
)
from synapsis.services.workflow_persistence import update_workflow_status
from synapsis.workflow_db import (
    update_workflow_run_step,
    save_workflow_run_message,
)


# Type alias -- any async callable that accepts a single dict
SendFn = Callable[[dict], Awaitable[None]]


async def stream_step(
    client: ClaudeSDKClient,
    send: SendFn,
    cancel_event: asyncio.Event,
    step_idx: int,
    step_log: dict,
    run_log: dict,
    workflow_id: str,
) -> Optional[str]:
    """Consume the SDK response stream for one step.

    Populates ``step_log`` with messages, timing, and cost data.
    Appends the completed ``step_log`` to ``run_log["steps"]``.

    Args:
        client:       The connected ClaudeSDKClient to stream from.
        send:         Async callable for sending events to the client.
        cancel_event: asyncio.Event for cancellation signalling.
        step_idx:     Zero-based index of this step in the pipeline.
        step_log:     Mutable step log dict to populate.
        run_log:      Mutable run log dict (step_log is appended to run_log["steps"]).
        workflow_id:  The workflow ID (for status updates on error).

    Returns:
        The concatenated text output for the step, or ``None`` if the
        stream was cancelled or raised a fatal exception.
    """
    # Import here to avoid circular dependency at module level
    from synapsis.services.workflow_step_runner import create_step_callbacks

    collected_text: list[str] = []
    streamed_text = False
    streamed_thinking = False
    accumulated_text = ""
    got_result = False
    step_start_time = time.time()

    # Wire up callbacks so the shared stream_core block handlers
    # perform workflow-specific persistence and transport.
    callbacks = create_step_callbacks(
        send, step_idx, step_log, run_log, collected_text,
    )

    try:
        async for message in client.receive_response():
            if cancel_event.is_set():
                break

            if isinstance(message, StreamEvent):
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            await send({"type": "text", "content": text, "step": step_idx})
                            streamed_text = True
                            accumulated_text += text
                    elif delta_type == "thinking_delta":
                        thinking = delta.get("thinking", "")
                        if thinking:
                            await send({"type": "thinking", "content": thinking, "step": step_idx})
                            streamed_thinking = True

            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if cancel_event.is_set():
                        break
                    if isinstance(block, TextBlock):
                        await handle_text_block(block, callbacks, already_streamed=streamed_text)
                        streamed_text = False
                    elif isinstance(block, ThinkingBlock):
                        await handle_thinking_block(block, callbacks, already_streamed=streamed_thinking)
                        streamed_thinking = False
                    elif isinstance(block, ToolUseBlock):
                        await handle_tool_use_block(block, callbacks)
                    elif isinstance(block, ToolResultBlock):
                        await handle_tool_result_block(block, callbacks)

            elif isinstance(message, SystemMessage):
                if message.subtype == "init" and isinstance(message.data, dict):
                    init_csid = message.data.get("session_id", "")
                    if init_csid:
                        step_log["session_id"] = init_csid
                if message.subtype == "api_key_source":
                    continue
                # Forward other system messages
                data_val = (
                    json.dumps(message.data) if isinstance(message.data, dict)
                    else str(message.data) if message.data is not None
                    else None
                )
                await send({
                    "type": "system",
                    "subtype": message.subtype,
                    "data": data_val,
                    "step": step_idx,
                })

            elif isinstance(message, ResultMessage):
                got_result = True
                await send({
                    "type": "result",
                    "estimated_cost": message.total_cost_usd,
                    "turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                    "session_id": message.session_id,
                    "is_error": message.is_error,
                    "step": step_idx,
                })
                step_log["estimated_cost_usd"] = message.total_cost_usd
                step_log["turns"] = message.num_turns
                step_log["session_id"] = message.session_id
                step_log["messages"].append({
                    "type": "result",
                    "estimated_cost": message.total_cost_usd,
                    "turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                    "session_id": message.session_id,
                    "timestamp": datetime.now().isoformat(),
                })
                try:
                    await save_workflow_run_message(
                        run_id=run_log["run_id"],
                        step_index=step_idx,
                        msg_type="result",
                        data={
                            "estimated_cost": message.total_cost_usd,
                            "turns": message.num_turns,
                            "duration_ms": message.duration_ms,
                            "session_id": message.session_id,
                        },
                        is_error=message.is_error or False,
                    )
                except Exception as e:
                    logger.debug("Failed to persist workflow message: %s", e)
                # Check for AUP/policy errors in accumulated text
                if accumulated_text and is_aup_error(accumulated_text):
                    await send({
                        "type": "aup_error",
                        "message": accumulated_text[:500],
                        "fallback_model": FALLBACK_MODEL,
                        "step": step_idx,
                    })

        # If the generator ended without a ResultMessage and the user did
        # not cancel, this almost always means the context window was exhausted.
        if not got_result and not cancel_event.is_set():
            logger.warning(
                "Workflow step %d ended without ResultMessage -- "
                "possible context window exhaustion", step_idx
            )
            await send({
                "type": "error",
                "message": CONTEXT_WINDOW_ERROR,
                "step": step_idx,
            })

    except asyncio.CancelledError:
        logger.info("Pipeline step %d cancelled", step_idx)
        step_log["error"] = "cancelled"
        step_log["completed_at"] = datetime.now().isoformat()
        step_log["duration_s"] = round(time.time() - step_start_time, 3)
        run_log["steps"].append(step_log)
        try:
            await update_workflow_run_step(
                run_id=run_log["run_id"],
                step_index=step_idx,
                error="cancelled",
                completed_at=time.time(),
                duration_s=step_log.get("duration_s"),
            )
        except Exception as e2:
            logger.debug("Failed to update workflow step error: %s", e2)
        return None

    except Exception as e:
        step_log["error"] = str(e)
        step_log["completed_at"] = datetime.now().isoformat()
        step_log["duration_s"] = round(time.time() - step_start_time, 3)
        run_log["steps"].append(step_log)
        try:
            await update_workflow_run_step(
                run_id=run_log["run_id"],
                step_index=step_idx,
                error=str(e),
                completed_at=time.time(),
                duration_s=step_log.get("duration_s"),
            )
        except Exception as e2:
            logger.debug("Failed to update workflow step error: %s", e2)
        await handle_stream_error(
            e,
            send=lambda payload: send({**payload, "step": step_idx}),
            context_label=f"workflow step {step_idx}",
        )
        await update_workflow_status(workflow_id, status="failed")
        return None

    # Happy-path finalisation
    full_output = "\n".join(collected_text)
    step_duration = time.time() - step_start_time

    step_log["output_text"] = full_output
    step_log["output_text_length"] = len(full_output)
    step_log["completed_at"] = datetime.now().isoformat()
    step_log["duration_s"] = round(step_duration, 3)
    run_log["steps"].append(step_log)

    # Persist step completion to the workflow runs database
    try:
        await update_workflow_run_step(
            run_id=run_log["run_id"],
            step_index=step_idx,
            output_text=full_output[:OUTPUT_TEXT_MAX_LENGTH] if full_output else None,
            tool_calls_count=step_log.get("tool_calls_count", 0),
            turns=step_log.get("turns"),
            estimated_cost=step_log.get("estimated_cost_usd"),
            claude_session_id=step_log.get("session_id"),
            completed_at=time.time(),
            duration_s=step_log.get("duration_s"),
        )
    except Exception as e:
        logger.warning("Failed to update workflow run step: %s", e)

    return full_output
