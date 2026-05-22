"""Workflow run CRUD operations."""

import json
import time
from typing import Optional

from synapsis.database.workflow_connection import _get_shared_workflow_db
from synapsis.utils.db_helpers import dynamic_update


async def create_workflow_run(
    run_id: str,
    workflow_id: str,
    workflow_name: str,
    initial_prompt: str,
    agent_sequence,
    step_count: int,
) -> None:
    """Insert a new workflow run record.

    Args:
        run_id:          Unique identifier for this pipeline run.
        workflow_id:     The workflow definition this run belongs to.
        workflow_name:   Human-readable workflow name.
        initial_prompt:  The original user prompt that started the run.
        agent_sequence:  List of agent IDs (or JSON string) in execution order.
        step_count:      Total number of steps in the pipeline.
    """
    db = await _get_shared_workflow_db()
    await db.execute(
        """INSERT INTO workflow_runs
           (id, workflow_id, workflow_name, status, started_at, initial_prompt, agent_sequence, step_count)
           VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
        (run_id, workflow_id, workflow_name, time.time(), initial_prompt,
         json.dumps(agent_sequence) if isinstance(agent_sequence, list) else agent_sequence,
         step_count),
    )
    await db.commit()


async def update_workflow_run(run_id: str, **kwargs) -> None:
    """Update a workflow run record with arbitrary fields.

    Args:
        run_id:  The run to update.
        kwargs:  Column name -> value pairs to set.
    """
    if not kwargs:
        return
    db = await _get_shared_workflow_db()
    await dynamic_update(db, "workflow_runs", "id", run_id, **kwargs)


async def get_workflow_runs(workflow_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Get all runs for a workflow, ordered by most recent first.

    Args:
        workflow_id: The workflow definition to filter by.
        limit:       Maximum number of rows to return.
        offset:      Number of rows to skip (for pagination).

    Returns:
        A list of run dicts.
    """
    db = await _get_shared_workflow_db()
    cursor = await db.execute(
        """SELECT * FROM workflow_runs
           WHERE workflow_id = ?
           ORDER BY started_at DESC
           LIMIT ? OFFSET ?""",
        (workflow_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_workflow_run(run_id: str) -> Optional[dict]:
    """Get a single workflow run by ID.

    Args:
        run_id: The run identifier to look up.

    Returns:
        A dict of run fields, or ``None`` if not found.
    """
    db = await _get_shared_workflow_db()
    cursor = await db.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_active_workflow_runs() -> list[dict]:
    """Get all currently running workflow runs.

    Returns:
        A list of run dicts with status ``'running'``, most recent first.
    """
    db = await _get_shared_workflow_db()
    cursor = await db.execute(
        "SELECT * FROM workflow_runs WHERE status = 'running' ORDER BY started_at DESC",
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def delete_workflow_run(run_id: str) -> None:
    """Delete a workflow run and all associated data (cascades).

    Args:
        run_id: The run identifier to delete.
    """
    db = await _get_shared_workflow_db()
    await db.execute("DELETE FROM workflow_runs WHERE id = ?", (run_id,))
    await db.commit()
