"""Workflow step runner -- single-step execution logic for pipeline workflows.

Split from workflow_executor.py (Phase 3A) to isolate per-step orchestration
(agent lookup, option building, client lifecycle, prompt construction,
streaming dispatch) from the top-level pipeline loop.
"""

from datetime import datetime
from typing import Callable, Awaitable, Optional

from synapsis.config import logger
from synapsis.constants import OUTPUT_PREVIEW_LENGTH
from synapsis.stream_callbacks import StreamCallbacks
from synapsis.session_manager import create_client_with_retry
from synapsis.services.workflow_persistence import update_workflow_status
from synapsis.services.workflow_step_helpers import (
    resolve_step_agent,
    build_step_options,
    create_step_log,
)
from synapsis.services.workflow_stream_handler import stream_step
from synapsis.workflow_db import (
    create_workflow_run_step,
    save_workflow_run_message,
)


# Type alias -- any async callable that accepts a single dict
SendFn = Callable[[dict], Awaitable[None]]


def build_step_prompt(
    step_idx: int,
    total_steps: int,
    agent_sequence: list[str],
    initial_prompt: str,
    current_prompt: str,
    step_prompts: list[str],
) -> str:
    """Construct the full prompt string for a single pipeline step.

    Step 0 receives the raw user prompt (plus any per-step instructions).
    Subsequent steps receive a structured context block containing the
    original task, the previous agent's output, and optional per-step
    instructions.
    """
    if step_idx == 0:
        step_prompt = current_prompt
        per_step = (
            step_prompts[0]
            if step_prompts and len(step_prompts) > 0 and step_prompts[0].strip()
            else ""
        )
        if per_step:
            step_prompt += f"\n\n## Additional Instructions\n{per_step}"
    else:
        previous_name = agent_sequence[step_idx - 1].replace("_", " ").title()
        per_step = (
            step_prompts[step_idx]
            if step_prompts and step_idx < len(step_prompts) and step_prompts[step_idx].strip()
            else ""
        )

        step_prompt = (
            f"## Workflow Pipeline Context\n\n"
            f"You are **Step {step_idx + 1} of {total_steps}** in a multi-agent workflow pipeline.\n\n"
            f"### Original Task\n{initial_prompt}\n\n"
            f"### Previous Step Output (from {previous_name})\n{current_prompt}\n\n"
        )

        if per_step:
            step_prompt += f"### Your Specific Instructions\n{per_step}\n\n"

        step_prompt += (
            f"---\n\n"
            f"**Important:** You have full access to the workspace at ~/workspace. "
            f"The previous agent may have created or modified files there. "
            f"Check for any relevant files, read them for context, and build on the previous work. "
            f"When you create or modify files, mention their full paths in your response "
            f"so the next agent in the pipeline can find them.\n"
        )

    return step_prompt


def create_step_callbacks(
    send: SendFn,
    step_idx: int,
    step_log: dict,
    run_log: dict,
    collected_text: list,
) -> StreamCallbacks:
    """Create StreamCallbacks wired for a workflow step.

    Used by stream_step to delegate block handling to the shared
    handlers in stream_core.py, avoiding duplication of block
    processing logic across Chat and Workflow paths.
    """
    async def _persist(msg_type: str, data: dict):
        step_log["messages"].append({
            **data, "type": msg_type,
            "timestamp": datetime.now().isoformat(),
        })
        if msg_type == "tool_use":
            step_log["tool_calls_count"] = step_log.get("tool_calls_count", 0) + 1
        # Also persist to DB
        try:
            await save_workflow_run_message(
                run_id=run_log["run_id"],
                step_index=step_idx,
                msg_type=msg_type,
                data=data,
                tool_use_id=data.get("tool_use_id"),
                is_error=data.get("is_error", False),
            )
        except Exception as e:
            logger.debug("Failed to persist workflow message: %s", e)

    async def _persist_sid(claude_sid: str):
        step_log["session_id"] = claude_sid

    async def _send(payload: dict):
        await send({**payload, "step": step_idx})

    return StreamCallbacks(
        send=_send,
        persist_message=_persist,
        persist_session_id=_persist_sid,
        on_text_complete=lambda text: collected_text.append(text),
        extra_fields={"step": step_idx},
    )


async def execute_step(
    send: SendFn,
    cancel_event,
    set_current_client: Callable,
    step_idx: int,
    agent_id: str,
    workflow: dict,
    run_log: dict,
    run_id: str,
    current_prompt: str,
    initial_prompt: str,
    total_steps: int,
    step_prompts: list[str],
) -> Optional[str]:
    """Run a single pipeline step and stream its output.

    Handles agent lookup, option building, client lifecycle, prompt
    construction, streaming, and step-level log assembly.

    Args:
        send:              Async callable for sending events to the client.
        cancel_event:      asyncio.Event for cancellation signalling.
        set_current_client: Callable to set the current client on the executor
                           (so the WebSocket handler can abort on cancel).
        step_idx:          Zero-based index of this step in the pipeline.
        agent_id:          The agent identifier string.
        workflow:          Full workflow dict (for stepConfigs, agentSequence, etc.).
        run_log:           Mutable run log dict that this method appends a step
                           entry to on completion or error.
        run_id:            UUID string for the current pipeline run.
        current_prompt:    The prompt/output carried forward from the previous
                           step (or the original user prompt for step 0).
        initial_prompt:    The original user-supplied prompt (unchanged for all
                           steps; embedded in context for steps > 0).
        total_steps:       Total number of steps in the pipeline.
        step_prompts:      Per-step override prompts from the frontend.

    Returns:
        The full text output of this step (to be used as ``current_prompt``
        for the next step), or ``None`` if a fatal error occurred (the
        error has already been sent to the client and the DB status updated).
    """
    workflow_id: str = workflow["id"]
    agent_sequence: list[str] = workflow.get("agentSequence", [])

    # Resolve agent definition and display name
    is_orchestrator, agent_def, agent_name = await resolve_step_agent(agent_id)

    if not is_orchestrator and not agent_def:
        await send({
            "type": "error",
            "message": f"Agent '{agent_id}' not found. Skipping step {step_idx + 1}.",
            "step": step_idx,
        })
        return current_prompt  # skip, not fatal -- keep going

    await send({
        "type": "step_start",
        "step": step_idx,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "total_steps": total_steps,
    })

    # Get step-specific config if available
    step_configs = workflow.get("stepConfigs", [])
    step_config = step_configs[step_idx] if step_idx < len(step_configs) else {}

    # Build agent options and step log
    opts = await build_step_options(is_orchestrator, agent_id, agent_def, step_config)
    step_log = create_step_log(step_idx, agent_id, agent_name, is_orchestrator, opts)

    # Create client and connect (with retry logic)
    try:
        client = await create_client_with_retry(opts)
    except Exception as e:
        # SDK connect can raise a variety of errors (network, auth, config);
        # treat any failure as fatal for this step.
        step_log["error"] = str(e)
        step_log["completed_at"] = datetime.now().isoformat()
        run_log["steps"].append(step_log)
        await send({
            "type": "error",
            "message": f"Failed to connect agent {agent_id}: {e}",
            "step": step_idx,
        })
        await update_workflow_status(workflow_id, status="failed")
        return None  # fatal
    set_current_client(client)

    # Build the prompt for this step, including per-step overrides and
    # richer context so each agent understands where it sits in the pipeline.
    step_prompt = build_step_prompt(
        step_idx=step_idx,
        total_steps=total_steps,
        agent_sequence=agent_sequence,
        initial_prompt=initial_prompt,
        current_prompt=current_prompt,
        step_prompts=step_prompts,
    )

    # Record the exact prompt sent to this agent
    step_log["input_prompt"] = step_prompt
    step_log["input_prompt_length"] = len(step_prompt)
    step_log["started_at"] = datetime.now().isoformat()

    # Persist the new step to the workflow runs database
    try:
        await create_workflow_run_step(
            run_id=run_log["run_id"],
            step_index=step_idx,
            agent_id=agent_id,
            agent_name=agent_name,
            model=getattr(opts, 'model', ''),
            input_prompt=step_prompt,
        )
    except Exception as e:
        logger.warning("Failed to persist workflow run step to DB: %s", e)

    try:
        await client.query(step_prompt)
    except Exception as e:
        # SDK query can raise a variety of errors (network, auth, rate-limit);
        # treat any failure as fatal for this step.
        step_log["error"] = str(e)
        step_log["completed_at"] = datetime.now().isoformat()
        run_log["steps"].append(step_log)
        await send({
            "type": "error",
            "message": f"Failed to query agent {agent_id}: {e}",
            "step": step_idx,
        })
        await update_workflow_status(workflow_id, status="failed")
        return None  # fatal

    # Stream responses, collecting full text output
    full_output = await stream_step(
        client=client,
        send=send,
        cancel_event=cancel_event,
        step_idx=step_idx,
        step_log=step_log,
        run_log=run_log,
        workflow_id=workflow_id,
    )

    # stream_step returns None on fatal streaming error
    if full_output is None:
        return None

    step_duration = step_log["duration_s"] or 0.0

    # Accumulate cost
    if step_log["estimated_cost_usd"] is not None:
        run_log["total_estimated_cost_usd"] = round(
            run_log["total_estimated_cost_usd"] + step_log["estimated_cost_usd"], 6
        )

    # Record inter-step data transfer (for all but the last step)
    next_step_idx = step_idx + 1
    if next_step_idx < total_steps:
        run_log["inter_step_data"].append({
            "from_step": step_idx,
            "to_step": next_step_idx,
            "data_passed": full_output,
            "data_length": len(full_output),
        })

    # Update progress
    progress = int(((step_idx + 1) / total_steps) * 100)
    await update_workflow_status(workflow_id, progress=progress)

    await send({
        "type": "step_complete",
        "step": step_idx,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "output_preview": full_output[:OUTPUT_PREVIEW_LENGTH],
        "duration_s": round(step_duration, 1),
    })

    return full_output
