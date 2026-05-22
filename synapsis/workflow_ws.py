"""
Workflow pipeline execution via WebSocket.

WS /ws/workflow/{workflow_id} — Execute a multi-agent pipeline with real-time streaming.

Protocol:
  Client sends: {"type": "run", "prompt": "...", "step_prompts": [...]}
                {"type": "attach", "run_id": "..."}
                {"type": "cancel", "run_id": "..."}
                {"type": "ping"}
  Server sends: step_start, text, thinking, tool_use, tool_result, result, step_complete,
                pipeline_complete, pipeline_cancelled, error, cancelled, run_started, attached

Pipelines run independently of WebSocket connections via the WorkflowRunManager.
Disconnecting does NOT cancel the pipeline — it continues in the background.
"""

import asyncio
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from synapsis.config import logger
from synapsis.database import get_db
from synapsis.ws_utils import forward_events, stop_forward_task, detach_and_stop


# ---------------------------------------------------------------------------
# Database helper (transport concern — used only by the WS handler)
# ---------------------------------------------------------------------------

async def _get_workflow(workflow_id: str) -> Optional[dict]:
    """Fetch a workflow from the database."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            step_configs_raw = row["step_configs"]
        except (KeyError, IndexError):
            step_configs_raw = "[]"

        return {
            "id": row["id"],
            "name": row["name"],
            "agentSequence": json.loads(row["agent_sequence"]),
            "initialPrompt": row["initial_prompt"],
            "nodes": json.loads(row["nodes"]),
            "edges": json.loads(row["edges"]),
            "status": row["status"],
            "runCount": row["run_count"],
            "stepConfigs": json.loads(step_configs_raw or "[]"),
        }


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def ws_workflow(websocket: WebSocket, workflow_id: str):
    """WebSocket handler for workflow pipeline execution.

    Supports multiple concurrent pipelines via the run manager.
    Disconnecting does NOT cancel the pipeline.
    """
    await websocket.accept()

    from synapsis.workflow_run_manager import run_manager

    current_run_id: Optional[str] = None
    current_queue: Optional[asyncio.Queue] = None
    forward_task: Optional[asyncio.Task] = None

    def _ws_connected() -> bool:
        return websocket.client_state == WebSocketState.CONNECTED

    async def _ws_send(event: dict) -> None:
        """Send an event dict to the WebSocket, breaking on send failure."""
        try:
            await websocket.send_json(event)
        except Exception:
            raise asyncio.CancelledError  # triggers clean exit from forward_events

    async def stop_forwarding():
        """Cancel the current forward task and wait for it to finish."""
        nonlocal forward_task
        await stop_forward_task(forward_task)
        forward_task = None

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = payload.get("type", "")

            if msg_type == "run":
                prompt = payload.get("prompt", "").strip()
                if not prompt:
                    await websocket.send_json({"type": "error", "message": "Prompt is required"})
                    continue

                step_prompts = payload.get("step_prompts", [])

                # Fetch workflow data
                workflow = await _get_workflow(workflow_id)
                if not workflow:
                    await websocket.send_json({"type": "error", "message": "Workflow not found"})
                    continue

                workflow_name = workflow.get("name", "")

                # Start run via manager
                run_id = await run_manager.start_run(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    prompt=prompt,
                    workflow=workflow,
                    step_prompts=step_prompts,
                )

                # Detach from previous run if any
                if current_run_id and current_queue:
                    run_manager.detach(current_run_id, current_queue)
                    await stop_forwarding()

                # Attach to the new run
                result = run_manager.attach(run_id)
                if result:
                    buffered, queue = result
                    current_run_id = run_id
                    current_queue = queue

                    # Send run_id to client
                    await websocket.send_json({"type": "run_started", "run_id": run_id})

                    # Send buffered events
                    for event in buffered:
                        await websocket.send_json(event)

                    # Start forwarding live events
                    forward_task = asyncio.create_task(
                        forward_events(queue, _ws_send, check_connected=_ws_connected)
                    )

            elif msg_type == "attach":
                run_id = payload.get("run_id", "")
                if not run_id:
                    await websocket.send_json({"type": "error", "message": "run_id is required"})
                    continue

                # Detach from previous run if any
                if current_run_id and current_queue:
                    run_manager.detach(current_run_id, current_queue)
                    await stop_forwarding()

                result = run_manager.attach(run_id)
                if result:
                    buffered, queue = result
                    current_run_id = run_id
                    current_queue = queue

                    await websocket.send_json({"type": "attached", "run_id": run_id})

                    # Send buffered events for hydration
                    for event in buffered:
                        await websocket.send_json(event)

                    # Start forwarding
                    forward_task = asyncio.create_task(
                        forward_events(queue, _ws_send, check_connected=_ws_connected)
                    )
                else:
                    await websocket.send_json({"type": "error", "message": f"Run {run_id} not found or expired"})

            elif msg_type == "cancel":
                run_id = payload.get("run_id", current_run_id)
                if run_id:
                    cancelled = await run_manager.cancel(run_id)
                    await websocket.send_json({
                        "type": "cancelled" if cancelled else "error",
                        "run_id": run_id,
                        "message": "" if cancelled else "Run not found or already finished",
                    })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Workflow WebSocket disconnected for %s (run continues in background)", workflow_id)
    except Exception as e:
        logger.exception("Workflow WebSocket error: %s", e)
    finally:
        # Detach but do NOT cancel — pipeline continues in background
        if current_run_id:
            await detach_and_stop(current_run_id, current_queue, forward_task, run_manager)
