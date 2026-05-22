"""
Workflow CRUD API — create, list, get, delete, and run workflows.

Workflows are persisted in SQLite (not in-memory) so they survive restarts.

- GET    /api/workflows              — List all workflows
- POST   /api/workflows              — Create a new workflow
- GET    /api/workflows/{id}         — Get a specific workflow
- PATCH  /api/workflows/{id}         — Partially update a workflow
- DELETE /api/workflows/{id}         — Delete a workflow
- POST   /api/workflows/{id}/run     — Mark workflow as running
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from synapsis.agents import SUBAGENTS, get_agent_display_name
from synapsis.database import get_db
from synapsis.utils.db_helpers import dynamic_update, fetch_one_or_404

router = APIRouter(prefix="/api", tags=["workflows"])


def _build_nodes(agent_sequence: list) -> list:
    """Generate ReactFlow nodes from an agent_sequence list."""
    nodes = []
    for i, agent_id in enumerate(agent_sequence):
        label = get_agent_display_name(agent_id)
        nodes.append({
            "id": f"node-{i}",
            "label": label,
            "status": "pending",
            "position": {"x": i * 250 + 50, "y": 100},
        })
    return nodes


def _build_edges(nodes: list) -> list:
    """Generate ReactFlow edges that connect consecutive nodes."""
    edges = []
    for i in range(len(nodes) - 1):
        edges.append({
            "id": f"edge-{i}",
            "source": f"node-{i}",
            "target": f"node-{i + 1}",
        })
    return edges


def _workflow_from_row(row) -> dict:
    """Convert a database row to a workflow dict.

    All keys use snake_case to match the frontend TypeScript ``Workflow``
    interface defined in ``frontend/src/lib/types-extended.ts``.

    If a stored workflow has an empty nodes/edges list but a non-empty
    agent_sequence (e.g. it was created before auto-generation was added),
    the nodes and edges are generated on the fly so the ReactFlow canvas
    always has something to render.
    """
    agent_sequence = json.loads(row["agent_sequence"])
    nodes = json.loads(row["nodes"])
    edges = json.loads(row["edges"])

    # Back-fill nodes/edges for workflows saved before auto-generation.
    if not nodes and agent_sequence:
        nodes = _build_nodes(agent_sequence)
    if not edges and len(nodes) > 1:
        edges = _build_edges(nodes)

    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "progress": row["progress"],
        "steps": row["steps"],
        "created_at": datetime.fromtimestamp(row["created_at"]).isoformat() if row["created_at"] else None,
        "updated_at": datetime.fromtimestamp(row["updated_at"]).isoformat() if row["updated_at"] else None,
        "last_run": datetime.fromtimestamp(row["last_run"]).isoformat() if row["last_run"] else None,
        "run_count": row["run_count"],
        "agent_sequence": agent_sequence,
        "initial_prompt": row["initial_prompt"],
        "nodes": nodes,
        "edges": edges,
        "step_configs": json.loads(row["step_configs"] or "[]"),
    }


@router.get("/workflows/runs/active")
async def get_active_runs():
    """Get all currently running workflow pipelines (in-memory run manager)."""
    from synapsis.workflow_run_manager import run_manager
    return {"runs": run_manager.get_active_runs()}


@router.get("/workflows")
async def list_workflows():
    """List all saved workflows."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM workflows ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return {"workflows": [_workflow_from_row(r) for r in rows]}


@router.post("/workflows")
async def create_workflow(payload: dict):
    """Create a new workflow (chain of agents)."""
    workflow_id = str(uuid.uuid4())[:8]
    now = time.time()

    agent_seq = payload.get("agentSequence") or payload.get("agent_sequence", [])
    step_configs = payload.get("stepConfigs") or payload.get("step_configs", [])

    # Validate agent IDs
    for agent_id in agent_seq:
        if agent_id not in ("orchestrator", "orchestrator_generic") and agent_id not in SUBAGENTS:
            # Check if it's a custom agent
            async with get_db() as db:
                cursor = await db.execute("SELECT id FROM agents WHERE id = ? AND is_active = 1", (agent_id,))
                if not await cursor.fetchone():
                    raise HTTPException(400, f"Unknown agent: {agent_id}")

    # Auto-generate nodes from agent_sequence when the caller omits them.
    nodes = payload.get("nodes") or []
    if not nodes and agent_seq:
        nodes = _build_nodes(agent_seq)

    # Auto-generate edges when the caller omits them.
    edges = payload.get("edges") or []
    if not edges and len(nodes) > 1:
        edges = _build_edges(nodes)

    async with get_db() as db:
        await db.execute("""
            INSERT INTO workflows (id, name, description, status, progress, steps,
                                   agent_sequence, initial_prompt, nodes, edges,
                                   created_at, updated_at, run_count, last_run, step_configs)
            VALUES (?, ?, ?, 'draft', 0, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
        """, (
            workflow_id,
            payload.get("name", "Untitled Workflow"),
            payload.get("description", ""),
            len(agent_seq),
            json.dumps(agent_seq),
            payload.get("initialPrompt") or payload.get("initial_prompt", ""),
            json.dumps(nodes),
            json.dumps(edges),
            now, now,
            json.dumps(step_configs),
        ))
        await db.commit()

        cursor = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        row = await cursor.fetchone()
        return _workflow_from_row(row)


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a specific workflow."""
    async with get_db() as db:
        row = await fetch_one_or_404(
            db,
            "SELECT * FROM workflows WHERE id = ?",
            (workflow_id,),
            "Workflow",
        )
        return _workflow_from_row(row)


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    async with get_db() as db:
        await db.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        await db.commit()
    return {"status": "deleted"}


@router.patch("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, payload: dict):
    """Partially update a workflow (PATCH semantics — only provided fields are changed)."""
    async with get_db() as db:
        row = await fetch_one_or_404(
            db,
            "SELECT * FROM workflows WHERE id = ?",
            (workflow_id,),
            "Workflow",
        )

        # Fields that may be updated and whether they need JSON serialization.
        json_fields = {"agent_sequence", "nodes", "edges", "step_configs"}
        allowed_fields = {"name", "description", "initial_prompt"} | json_fields

        update_fields = {}
        for field in allowed_fields:
            if field in payload:
                value = payload[field]
                if field in json_fields:
                    value = json.dumps(value)
                update_fields[field] = value

        if not update_fields:
            # Nothing to update -- just return the current workflow.
            return _workflow_from_row(row)

        await dynamic_update(
            db, "workflows", "id", workflow_id,
            extra_sets={"updated_at": time.time()},
            **update_fields,
        )

        cursor = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        updated_row = await cursor.fetchone()
        return _workflow_from_row(updated_row)


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str):
    """Mark a workflow as running. Actual execution happens via WebSocket."""
    async with get_db() as db:
        await fetch_one_or_404(
            db,
            "SELECT * FROM workflows WHERE id = ?",
            (workflow_id,),
            "Workflow",
        )

        now = time.time()
        await db.execute("""
            UPDATE workflows SET status = 'running', progress = 0,
                                 run_count = run_count + 1, last_run = ?, updated_at = ?
            WHERE id = ?
        """, (now, now, workflow_id))
        await db.commit()

        cursor = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        row = await cursor.fetchone()
        return {"status": "started", "workflow": _workflow_from_row(row)}


# ---------------------------------------------------------------------------
# Run log endpoints
# ---------------------------------------------------------------------------

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
