"""Workflow Run Manager — manages concurrent pipeline executions independently of WebSocket connections.

Executors run as background asyncio tasks. WebSocket connections attach/detach
as subscribers without affecting execution lifecycle.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from synapsis.config import logger
from synapsis.database import get_db
from synapsis.services.workflow_executor import WorkflowExecutor
from synapsis.workflow_db import update_workflow_run


@dataclass
class RunHandle:
    """Represents a running or recently-completed pipeline execution."""
    run_id: str
    workflow_id: str
    workflow_name: str
    status: str = "running"  # running, completed, cancelled, failed
    started_at: float = field(default_factory=time.time)
    task: Optional[asyncio.Task] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    event_buffer: list = field(default_factory=list)
    subscribers: list = field(default_factory=list)  # list of asyncio.Queue
    executor: Optional[WorkflowExecutor] = None


class WorkflowRunManager:
    """Singleton that owns workflow executor lifecycles independently of WebSocket connections."""

    def __init__(self):
        self._active_runs: dict[str, RunHandle] = {}
        self._retention_seconds = 3600  # keep completed runs for 1 hour

    async def start_run(self, workflow_id: str, workflow_name: str, prompt: str,
                        workflow: dict, step_prompts: list = None) -> str:
        """Start a new pipeline execution. Returns the run_id."""
        run_id = str(uuid.uuid4())
        handle = RunHandle(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
        )

        # Create send callback that buffers events AND forwards to subscribers
        async def send_event(event: dict):
            event["run_id"] = run_id
            handle.event_buffer.append(event)
            # Forward to all active subscribers
            disconnected = []
            for i, queue in enumerate(handle.subscribers):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Subscriber queue full for run %s, dropping event", run_id)
                except Exception:
                    disconnected.append(i)
            # Clean up disconnected subscribers
            for i in reversed(disconnected):
                handle.subscribers.pop(i)

        executor = WorkflowExecutor(send=send_event, cancel_event=handle.cancel_event)
        handle.executor = executor

        # Start the pipeline as a background task
        async def run_pipeline():
            try:
                await executor.execute_pipeline(
                    prompt=prompt,
                    workflow=workflow,
                    step_prompts=step_prompts or [],
                    run_id=run_id,
                )
                handle.status = "completed"
            except asyncio.CancelledError:
                handle.status = "cancelled"
                logger.info("Pipeline %s was cancelled", run_id)
            except Exception as e:
                handle.status = "failed"
                logger.exception("Pipeline %s failed: %s", run_id, e)
            finally:
                # Send terminal event
                terminal_event = {
                    "type": "pipeline_status",
                    "run_id": run_id,
                    "status": handle.status,
                }
                handle.event_buffer.append(terminal_event)
                for queue in handle.subscribers:
                    try:
                        queue.put_nowait(terminal_event)
                    except Exception:
                        pass

                # Schedule cleanup after retention period
                loop = asyncio.get_running_loop()
                loop.call_later(
                    self._retention_seconds,
                    lambda rid=run_id: self._active_runs.pop(rid, None)
                )

        handle.task = asyncio.create_task(run_pipeline())
        self._active_runs[run_id] = handle

        # Increment run_count and update last_run on the workflows table so
        # the frontend can rely on run_count for display purposes.
        try:
            async with get_db() as db:
                now = time.time()
                await db.execute(
                    "UPDATE workflows SET run_count = run_count + 1, last_run = ?, updated_at = ? WHERE id = ?",
                    (now, now, workflow_id),
                )
                await db.commit()
        except Exception as e:
            logger.warning("Failed to increment run_count for workflow %s: %s", workflow_id, e)

        logger.info("Started workflow run %s for workflow %s", run_id, workflow_id)
        return run_id

    def attach(self, run_id: str) -> Optional[tuple[list, asyncio.Queue]]:
        """Attach a subscriber to a running pipeline.

        Returns (buffered_events, live_queue) or None if run not found.
        """
        handle = self._active_runs.get(run_id)
        if not handle:
            return None

        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        handle.subscribers.append(queue)

        # Return a snapshot of buffered events + the live queue
        return list(handle.event_buffer), queue

    def detach(self, run_id: str, queue: asyncio.Queue):
        """Detach a subscriber from a pipeline (does NOT cancel the run)."""
        handle = self._active_runs.get(run_id)
        if handle:
            try:
                handle.subscribers.remove(queue)
            except ValueError:
                pass

    async def cancel(self, run_id: str) -> bool:
        """Cancel a running pipeline."""
        handle = self._active_runs.get(run_id)
        if not handle or handle.status != "running":
            return False

        handle.cancel_event.set()
        if handle.task and not handle.task.done():
            handle.task.cancel()
            try:
                await asyncio.wait_for(handle.task, timeout=10.0)
            except asyncio.TimeoutError:
                # Task didn't finish in time -- force status since the
                # task's own finally block may not have run yet.
                handle.status = "cancelled"
            except asyncio.CancelledError:
                pass
            # If the task finished within the timeout, its own finally block
            # already set handle.status -- don't overwrite it here.
        else:
            # Task already done or absent -- just mark cancelled
            handle.status = "cancelled"

        logger.info("Cancelled workflow run %s (status=%s)", run_id, handle.status)
        return True

    def get_active_runs(self) -> list[dict]:
        """Return summaries of all active/recent runs."""
        result = []
        for handle in self._active_runs.values():
            result.append({
                "run_id": handle.run_id,
                "workflow_id": handle.workflow_id,
                "workflow_name": handle.workflow_name,
                "status": handle.status,
                "started_at": handle.started_at,
                "event_count": len(handle.event_buffer),
                "subscriber_count": len(handle.subscribers),
            })
        return result

    def get_run(self, run_id: str) -> Optional[RunHandle]:
        """Get a specific run handle."""
        return self._active_runs.get(run_id)

    def is_running(self, run_id: str) -> bool:
        """Check if a run is currently active."""
        handle = self._active_runs.get(run_id)
        return handle is not None and handle.status == "running"

    async def shutdown(self):
        """Cancel all running pipelines during app shutdown."""
        for run_id in list(self._active_runs.keys()):
            await self.cancel(run_id)
        self._active_runs.clear()


# Singleton instance
run_manager = WorkflowRunManager()
