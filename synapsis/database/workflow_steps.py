"""Workflow run step CRUD operations."""

import time

from synapsis.database.workflow_connection import _get_shared_workflow_db
from synapsis.utils.db_helpers import dynamic_update


async def create_workflow_run_step(
    run_id: str,
    step_index: int,
    agent_id: str,
    agent_name: str,
    model: str,
    input_prompt: str,
) -> None:
    """Insert a new workflow run step record.

    Args:
        run_id:       The parent run identifier.
        step_index:   Zero-based step position in the pipeline.
        agent_id:     Agent identifier string.
        agent_name:   Human-readable agent name.
        model:        Model identifier used for this step.
        input_prompt: The prompt sent to this agent.
    """
    db = await _get_shared_workflow_db()
    await db.execute(
        """INSERT INTO workflow_run_steps
           (run_id, step_index, agent_id, agent_name, model, input_prompt, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, step_index, agent_id, agent_name, model, input_prompt, time.time()),
    )
    await db.commit()


async def update_workflow_run_step(run_id: str, step_index: int, **kwargs) -> None:
    """Update a workflow run step record.

    Args:
        run_id:     The parent run identifier.
        step_index: Zero-based step position to update.
        kwargs:     Column name -> value pairs to set.
    """
    if not kwargs:
        return
    db = await _get_shared_workflow_db()
    await dynamic_update(
        db, "workflow_run_steps",
        "run_id = ? AND step_index", (run_id, step_index),
        **kwargs,
    )


async def get_workflow_run_steps(run_id: str) -> list[dict]:
    """Get all steps for a workflow run, ordered by step index.

    Args:
        run_id: The run identifier.

    Returns:
        A list of step dicts.
    """
    db = await _get_shared_workflow_db()
    cursor = await db.execute(
        "SELECT * FROM workflow_run_steps WHERE run_id = ? ORDER BY step_index",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
