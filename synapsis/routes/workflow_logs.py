"""
Workflow file-based run log endpoints.

Serves run logs stored as JSON files on the filesystem
(~/workspace/workflow_logs/).

- GET    /api/workflows/{id}/logs            — List run logs for a workflow
- GET    /api/workflows/{id}/logs/{filename} — Download a specific log file
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api", tags=["workflow-logs"])

_LOG_DIR = Path.home() / "workspace" / "workflow_logs"


@router.get("/workflows/{workflow_id}/logs")
async def list_workflow_logs(workflow_id: str):
    """List all run logs saved for a specific workflow.

    Scans ~/workspace/workflow_logs/ for JSON files matching the pattern
    ``{workflow_id}_*.json`` and returns a summary of each run.

    Returns:
        A JSON object with a ``logs`` list. Each entry contains:
        ``run_id``, ``filename``, ``status``, ``started_at``,
        ``completed_at``, ``total_duration_s``, and ``file_path``.
    """
    if not _LOG_DIR.exists():
        return {"logs": []}

    pattern = f"{workflow_id}_*.json"
    log_files = sorted(_LOG_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    summaries = []
    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            summaries.append({
                "run_id": data.get("run_id"),
                "filename": log_file.name,
                "status": data.get("status"),
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
                "total_duration_s": data.get("total_duration_s"),
                "total_estimated_cost_usd": data.get("total_estimated_cost_usd"),
                "file_path": str(log_file),
            })
        except (json.JSONDecodeError, OSError, KeyError):
            # Skip any log files that cannot be opened or parsed
            continue

    return {"logs": summaries}


@router.get("/workflows/{workflow_id}/logs/{filename}")
async def download_workflow_log(workflow_id: str, filename: str):
    """Download a specific run log JSON file.

    The ``filename`` must match a file stored in ~/workspace/workflow_logs/
    and must start with the given ``workflow_id`` to prevent path traversal.

    Returns:
        The raw JSON log file as a download attachment.
    """
    # Security: reject any filename that doesn't belong to this workflow or
    # that contains path-traversal sequences.
    if not filename.startswith(f"{workflow_id}_") or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid log filename")

    log_file = _LOG_DIR / filename
    if not log_file.exists():
        raise HTTPException(404, "Log file not found")

    return FileResponse(
        path=str(log_file),
        media_type="application/json",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
