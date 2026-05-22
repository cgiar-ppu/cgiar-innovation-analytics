"""Workflow persistence helpers -- run log file I/O and database status updates.

Split from workflow_executor.py (Phase 3A) to isolate persistence concerns
from orchestration logic.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from synapsis.config import logger
from synapsis.database import get_db
from synapsis.utils.db_helpers import dynamic_update


def save_run_log(run_log: dict) -> str:
    """Persist a pipeline run log to ~/workspace/workflow_logs/.

    Creates the directory if it does not exist, then writes the log as a
    pretty-printed JSON file.

    Args:
        run_log: The fully populated run log dict.

    Returns:
        The absolute path to the saved JSON file as a string.
    """
    log_dir = Path.home() / "workspace" / "workflow_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    workflow_id = run_log.get("workflow_id", "unknown")
    run_id = run_log.get("run_id", "unknown")
    # Use a filesystem-safe timestamp (colons replaced with dashes)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    filename = f"{workflow_id}_{run_id}_{ts}.json"
    file_path = log_dir / filename

    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(run_log, fh, indent=2, default=str)

    logger.info("Run log saved to %s", file_path)
    return str(file_path)


async def update_workflow_status(workflow_id: str, **kwargs):
    """Update workflow fields in the database.

    Automatically sets ``updated_at`` to the current timestamp alongside
    whatever fields are passed via **kwargs.
    """
    if not kwargs:
        return
    async with get_db() as db:
        await dynamic_update(
            db, "workflows", "id", workflow_id,
            extra_sets={"updated_at": time.time()},
            **kwargs,
        )
