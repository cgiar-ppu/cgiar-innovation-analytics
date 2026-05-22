"""
Workflow run history endpoints (DB-backed).

Provides endpoints for listing, viewing, downloading, and continuing
from workflow runs stored in the workflow database.

- GET    /api/workflows/{id}/runs                    — List runs for a workflow
- GET    /api/workflows/{id}/runs/{run_id}           — Get full run detail
- GET    /api/workflows/{id}/runs/{run_id}/download  — Download run log
- POST   /api/workflows/{id}/runs/{run_id}/continue  — Continue from run output
"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from starlette.responses import Response

from synapsis.utils.db_helpers import parse_json_field

router = APIRouter(prefix="/api", tags=["workflow-runs"])


@router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs(workflow_id: str, limit: int = 50, offset: int = 0):
    """List all runs for a workflow."""
    from synapsis.workflow_db import get_workflow_runs
    runs = await get_workflow_runs(workflow_id, limit=limit, offset=offset)
    # Parse agent_sequence from JSON string back to list
    for run in runs:
        parse_json_field(run, "agent_sequence")
    return {"runs": runs, "total": len(runs)}


@router.get("/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run_detail(workflow_id: str, run_id: str):
    """Get full run detail with steps and messages."""
    from synapsis.workflow_db import (
        get_workflow_run, get_workflow_run_steps, get_workflow_run_messages,
    )

    run = await get_workflow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = await get_workflow_run_steps(run_id)

    # Attach messages to each step
    for step in steps:
        step_msgs = await get_workflow_run_messages(run_id, step["step_index"])
        # Parse data field from JSON
        for msg in step_msgs:
            parse_json_field(msg, "data")
        step["messages"] = step_msgs

    # Parse agent_sequence
    parse_json_field(run, "agent_sequence")

    run["steps"] = steps
    return run


@router.get("/workflows/{workflow_id}/runs/{run_id}/download")
async def download_workflow_run(workflow_id: str, run_id: str, format: str = "json"):
    """Download a workflow run log in various formats."""
    from synapsis.workflow_db import get_workflow_run

    run = await get_workflow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Try to find the log file on disk first (it has the richest data)
    log_filename = run.get("log_filename")
    log_data = None

    if log_filename:
        log_path = Path(log_filename)
        if not log_path.exists():
            # Try relative to workflow_logs dir
            from synapsis.config import WORKSPACE
            log_path = Path(WORKSPACE) / "workflow_logs" / Path(log_filename).name
        if log_path.exists():
            try:
                log_data = json.loads(log_path.read_text())
            except Exception:
                pass

    if format == "json":
        if log_data:
            return JSONResponse(content=log_data)
        # Fallback: build from DB
        detail = await get_workflow_run_detail(workflow_id, run_id)
        return JSONResponse(content=detail)

    elif format == "md":
        from synapsis.exporters.workflow_run import export_workflow_run_markdown
        source = log_data or await get_workflow_run_detail(workflow_id, run_id)
        content, filename = export_workflow_run_markdown(source)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif format == "html":
        from synapsis.exporters.workflow_run import export_workflow_run_html
        source = log_data or await get_workflow_run_detail(workflow_id, run_id)
        content, filename = export_workflow_run_html(source)
        return Response(
            content=content,
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")


@router.post("/workflows/{workflow_id}/runs/{run_id}/continue")
async def continue_from_workflow_run(workflow_id: str, run_id: str):
    """Create a new chat session pre-seeded with workflow output context."""
    from synapsis.workflow_db import get_workflow_run, get_workflow_run_steps
    from synapsis.database import create_session, save_message, save_initial_context
    from synapsis.services.workflow_service import build_continuation_context

    run = await get_workflow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = await get_workflow_run_steps(run_id)

    # Create a new chat session
    session_id = str(uuid.uuid4())[:8]
    workflow_name = run.get("workflow_name", "Workflow")
    title = f"Continue: {workflow_name}"

    await create_session(session_id, title)

    # Build and insert context message
    context_content = build_continuation_context(run, steps)

    await save_message(session_id, "system", {"content": context_content, "subtype": "workflow_context"})

    # Also store the context on the session so it can be prepended to the
    # first user message sent to the Claude SDK (the system message above is
    # only visible in the UI — the SDK starts a fresh conversation and has no
    # access to DB-stored messages).
    await save_initial_context(session_id, context_content)

    return {"session_id": session_id, "title": title}
