"""Workflow run message operations."""

import json
import time
from typing import Optional

from synapsis.database.workflow_connection import _get_shared_workflow_db


async def save_workflow_run_message(
    run_id: str,
    step_index: int,
    msg_type: str,
    data,
    tool_use_id: Optional[str] = None,
    is_error: bool = False,
) -> None:
    """Save an individual message from a workflow run step.

    Args:
        run_id:      The parent run identifier.
        step_index:  Zero-based step position this message belongs to.
        msg_type:    Message type label (text, thinking, tool_use, tool_result, result).
        data:        Message payload; dicts are JSON-serialized.
        tool_use_id: Optional tool use identifier for tool_use/tool_result messages.
        is_error:    Whether this message represents an error.
    """
    db = await _get_shared_workflow_db()
    await db.execute(
        """INSERT INTO workflow_run_messages
           (run_id, step_index, ts, type, data, tool_use_id, is_error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, step_index, time.time(), msg_type,
         json.dumps(data) if isinstance(data, dict) else data,
         tool_use_id, 1 if is_error else 0),
    )
    await db.commit()


async def get_workflow_run_messages(
    run_id: str, step_index: Optional[int] = None,
) -> list[dict]:
    """Get messages for a workflow run, optionally filtered by step.

    Args:
        run_id:     The run identifier.
        step_index: If provided, only return messages for this step.

    Returns:
        A list of message dicts ordered by timestamp.
    """
    db = await _get_shared_workflow_db()
    if step_index is not None:
        cursor = await db.execute(
            """SELECT * FROM workflow_run_messages
               WHERE run_id = ? AND step_index = ?
               ORDER BY ts""",
            (run_id, step_index),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM workflow_run_messages WHERE run_id = ? ORDER BY ts",
            (run_id,),
        )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
