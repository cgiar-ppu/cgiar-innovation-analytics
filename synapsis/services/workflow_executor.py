"""
WorkflowExecutor -- business logic for multi-agent pipeline execution.

Encapsulates the full pipeline run lifecycle:
- Step iteration and prompt chaining
- Delegation to workflow_step_runner for per-step execution
- Database status updates via workflow_persistence
- Run log persistence via workflow_persistence
- Pipeline-level result logging

The class is intentionally transport-agnostic: it communicates back to the
caller exclusively via a ``send`` coroutine injected at construction time,
so the same executor can be driven by a WebSocket handler, an HTTP handler,
or a test harness without any changes here.
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Callable, Awaitable, Optional

from claude_agent_sdk import ClaudeSDKClient

from synapsis.config import logger
from synapsis.database import get_db
from synapsis.services.workflow_persistence import save_run_log, update_workflow_status
from synapsis.services.workflow_step_runner import execute_step
from synapsis.workflow_db import create_workflow_run, update_workflow_run


# Type alias -- any async callable that accepts a single dict
SendFn = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# WorkflowExecutor
# ---------------------------------------------------------------------------

class WorkflowExecutor:
    """Executes a multi-agent workflow pipeline.

    The executor is instantiated once per pipeline run (or per WebSocket
    connection) and communicates back to the client through the ``send``
    callback provided at construction time.

    Args:
        send:         Async callable ``(dict) -> None`` used to stream events
                      back to the caller (WebSocket, test, etc.).
        cancel_event: ``asyncio.Event`` that any external actor (e.g. a cancel
                      message handler) can set to request mid-run cancellation.
    """

    def __init__(self, send: SendFn, cancel_event: asyncio.Event):
        self._send = send
        self._cancel_event = cancel_event
        # Exposed so the WebSocket handler can abort the active client on cancel
        self.current_client: Optional[ClaudeSDKClient] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_pipeline(
        self,
        prompt: str,
        workflow: dict,
        step_prompts: list[str] = [],
        run_id: Optional[str] = None,
    ) -> None:
        """Execute all agents in sequence, streaming each one's output.

        Args:
            prompt:       The initial user prompt that kicks off the pipeline.
            workflow:     The workflow definition dict (as returned by
                          ``_get_workflow`` in workflow_ws.py).
            step_prompts: Optional per-step override prompts sent by the
                          frontend.  Index corresponds to step position;
                          empty strings are ignored.
            run_id:       Optional externally-provided run identifier.  When
                          the executor is driven by the WorkflowRunManager the
                          manager passes its own run_id so that the DB records
                          match the ID the frontend receives.  When omitted a
                          new UUID is generated automatically.
        """
        workflow_id: str = workflow["id"]
        initial_prompt = prompt
        agent_sequence: list[str] = workflow.get("agentSequence", [])
        total_steps = len(agent_sequence)

        if total_steps == 0:
            await self._send({"type": "error", "message": "Workflow has no agents in sequence."})
            return

        now = time.time()
        await update_workflow_status(workflow_id, status="running", progress=0, last_run=now)
        # Increment run_count separately since update_workflow_status uses simple
        # parameter substitution and cannot do run_count = run_count + 1.
        async with get_db() as db:
            await db.execute(
                "UPDATE workflows SET run_count = run_count + 1 WHERE id = ?",
                (workflow_id,),
            )
            await db.commit()

        current_prompt = prompt
        pipeline_start = time.time()
        pipeline_started_at = datetime.now().isoformat()

        # ------------------------------------------------------------------
        # Initialise the comprehensive run log for this pipeline execution
        # ------------------------------------------------------------------
        if run_id is None:
            run_id = str(uuid.uuid4())
        run_log: dict = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow.get("name", workflow_id),
            "started_at": pipeline_started_at,
            "completed_at": None,
            "status": "running",
            "total_duration_s": None,
            "initial_prompt": initial_prompt,
            "agent_sequence": agent_sequence,
            "step_prompts": list(step_prompts),
            "steps": [],
            "total_estimated_cost_usd": 0.0,
            "inter_step_data": [],
            "metadata": {
                "synapsis_version": "2.0.0",
                "platform": "macos",
                "log_format_version": "1.0",
            },
        }

        # Persist the new run to the workflow runs database
        try:
            await create_workflow_run(
                run_id=run_log["run_id"],
                workflow_id=run_log["workflow_id"],
                workflow_name=run_log.get("workflow_name", ""),
                initial_prompt=prompt,
                agent_sequence=agent_sequence,
                step_count=len(agent_sequence),
            )
        except Exception as e:
            logger.warning("Failed to persist workflow run to DB: %s", e)

        # Track last completed step index for the cancellation message
        last_step_idx = 0

        for step_idx, agent_id in enumerate(agent_sequence):
            last_step_idx = step_idx
            if self._cancel_event.is_set():
                break

            current_prompt = await execute_step(
                send=self._send,
                cancel_event=self._cancel_event,
                set_current_client=self._set_current_client,
                step_idx=step_idx,
                agent_id=agent_id,
                workflow=workflow,
                run_log=run_log,
                run_id=run_id,
                current_prompt=current_prompt,
                initial_prompt=initial_prompt,
                total_steps=total_steps,
                step_prompts=step_prompts,
            )

            # execute_step returns None on fatal error (already handled internally)
            if current_prompt is None:
                return

            if self._cancel_event.is_set():
                break

        # ------------------------------------------------------------------
        # Pipeline complete -- finalise and persist the run log
        # ------------------------------------------------------------------
        total_duration = time.time() - pipeline_start
        run_log["completed_at"] = datetime.now().isoformat()
        run_log["total_duration_s"] = round(total_duration, 3)

        await self._log_pipeline_result(
            run_log=run_log,
            run_id=run_id,
            workflow_id=workflow_id,
            total_steps=total_steps,
            total_duration=total_duration,
            last_step_idx=last_step_idx,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _set_current_client(self, client: ClaudeSDKClient) -> None:
        """Callback passed to execute_step so it can expose the active client."""
        self.current_client = client

    async def _log_pipeline_result(
        self,
        run_log: dict,
        run_id: str,
        workflow_id: str,
        total_steps: int,
        total_duration: float,
        last_step_idx: int,
    ) -> None:
        """Finalize run_log status, persist to disk, and send the terminal event.

        Handles both the cancelled and completed cases.
        """
        # Capture a summary from the last step's output (first 500 chars)
        summary = None
        if run_log.get("steps"):
            last_output = run_log["steps"][-1].get("output_text", "")
            if last_output:
                summary = last_output[:500]
        run_log["summary"] = summary

        if self._cancel_event.is_set():
            run_log["status"] = "cancelled"
            await update_workflow_status(workflow_id, status="cancelled")
            try:
                log_file_path = save_run_log(run_log)
            except OSError as log_err:
                logger.warning("Failed to save run log: %s", log_err)
                log_file_path = None
            run_log["log_filename"] = log_file_path
            await self._send({
                "type": "pipeline_cancelled",
                "completed_steps": last_step_idx,
                "run_log_id": run_id,
                "run_log_path": log_file_path,
            })
        else:
            run_log["status"] = "completed"
            await update_workflow_status(workflow_id, status="completed", progress=100)
            try:
                log_file_path = save_run_log(run_log)
            except OSError as log_err:
                logger.warning("Failed to save run log: %s", log_err)
                log_file_path = None
            run_log["log_filename"] = log_file_path
            await self._send({
                "type": "pipeline_complete",
                "total_steps": total_steps,
                "total_duration_s": round(total_duration, 1),
                "run_log_id": run_id,
                "run_log_path": log_file_path,
            })

        # Persist pipeline completion to the workflow runs database
        try:
            await update_workflow_run(
                run_log["run_id"],
                status=run_log["status"],
                completed_at=time.time(),
                total_duration_s=run_log.get("total_duration_s"),
                total_cost_usd=run_log.get("total_estimated_cost_usd"),
                completed_steps=len([s for s in run_log.get("steps", []) if not s.get("error")]),
                progress=100 if run_log["status"] == "completed" else run_log.get("progress", 0),
                log_filename=run_log.get("log_filename"),
                summary=summary,
            )
        except Exception as e:
            logger.warning("Failed to update workflow run in DB: %s", e)
