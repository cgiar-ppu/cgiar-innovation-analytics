"""
Fleet management REST API routes.

- GET    /api/fleet                              -- List all fleets
- POST   /api/fleet                              -- Create a new fleet
- GET    /api/fleet/health                       -- System health metrics
- GET    /api/fleet/agent/{agent_id}/messages     -- Agent message history
- POST   /api/fleet/agent/{agent_id}/resume       -- Resume a specific agent
- GET    /api/fleet/run/{run_id}                 -- Get run details
- GET    /api/fleet/{fleet_id}                   -- Get fleet details + agents
- PATCH  /api/fleet/{fleet_id}                   -- Update fleet metadata
- DELETE /api/fleet/{fleet_id}                   -- Archive a fleet
- GET    /api/fleet/{fleet_id}/agents            -- List agents in a fleet
- GET    /api/fleet/{fleet_id}/agents/{agent_id} -- Agent details + messages
- POST   /api/fleet/{fleet_id}/spawn             -- Spawn agents (batch run)
- POST   /api/fleet/{fleet_id}/broadcast         -- Broadcast to all agents
- POST   /api/fleet/{fleet_id}/mediate           -- Mediate between two agents
- GET    /api/fleet/{fleet_id}/runs              -- List runs for a fleet
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from synapsis.config import logger

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class FleetCreate(BaseModel):
    name: str
    description: str = ""
    project_path: str = ""
    tags: list[str] = []
    config: dict = {}

class FleetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None

class SpawnRequest(BaseModel):
    agents: list[dict]
    concurrency: int = 3
    initial_task: str = ""

class BroadcastRequest(BaseModel):
    message: str

class MediateRequest(BaseModel):
    agent_a: str
    agent_b: str
    topic: str

class ResumeRequest(BaseModel):
    message: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert an aiosqlite Row to a plain dict for JSON serialization."""
    if row is None:
        return {}
    return row if isinstance(row, dict) else dict(row)

def _rows_to_list(rows) -> list[dict]:
    """Convert a list of aiosqlite Rows to a list of dicts."""
    return [_row_to_dict(r) for r in rows]

async def _require_fleet(fleet_id: str):
    """Fetch a fleet or raise 404."""
    from synapsis.database.fleet_operations import get_fleet as db_get_fleet
    fleet = await db_get_fleet(fleet_id)
    if not fleet:
        raise HTTPException(404, f"Fleet '{fleet_id}' not found")
    return fleet


# ---------------------------------------------------------------------------
# Fleet CRUD
# ---------------------------------------------------------------------------

@router.get("")
async def list_fleets(status: Optional[str] = None):
    """List all fleets, optionally filtered by status."""
    try:
        from synapsis.database.fleet_operations import list_fleets as db_list_fleets
        fleets = await db_list_fleets(status=status)
        return {"status": "ok", "fleets": _rows_to_list(fleets)}
    except Exception as e:
        logger.exception("Failed to list fleets: %s", e)
        raise HTTPException(500, f"Failed to list fleets: {e}")

@router.post("")
async def create_fleet(payload: FleetCreate):
    """Create a new fleet."""
    if not payload.name or not payload.name.strip():
        raise HTTPException(400, "Fleet name is required")
    try:
        from synapsis.database.fleet_operations import create_fleet as db_create_fleet
        fleet = await db_create_fleet(
            name=payload.name, description=payload.description,
            project_path=payload.project_path, tags=payload.tags,
            config=payload.config,
        )
        return {"status": "ok", "fleet": _row_to_dict(fleet)}
    except Exception as e:
        logger.exception("Failed to create fleet: %s", e)
        raise HTTPException(500, f"Failed to create fleet: {e}")

@router.get("/health")
async def fleet_health():
    """Get system health metrics for the fleet subsystem."""
    try:
        from synapsis.services.fleet_manager import fleet_manager
        metrics = await fleet_manager.get_system_health()
        return {"status": "ok", **metrics}
    except Exception as e:
        logger.exception("Failed to get fleet health: %s", e)
        raise HTTPException(500, f"Failed to get fleet health: {e}")

@router.get("/agent/{agent_id}/messages")
async def get_agent_messages(agent_id: str):
    """Get message history for a specific fleet agent."""
    try:
        from synapsis.database.fleet_operations import get_agent_messages as db_get_msgs
        messages = await db_get_msgs(agent_id)
        return {"status": "ok", "messages": _rows_to_list(messages)}
    except Exception as e:
        logger.exception("Failed to get agent messages: %s", e)
        raise HTTPException(500, f"Failed to get agent messages: {e}")

@router.post("/agent/{agent_id}/resume")
async def resume_agent(agent_id: str, payload: ResumeRequest):
    """Resume a specific fleet agent with an optional message."""
    try:
        from synapsis.services.fleet_manager import fleet_manager
        result = await fleet_manager.resume_agent(agent_id, message=payload.message)
        return {"status": "ok", "agent_id": agent_id, **result}
    except Exception as e:
        logger.exception("Failed to resume agent %s: %s", agent_id, e)
        raise HTTPException(500, f"Failed to resume agent: {e}")

@router.get("/run/{run_id}")
async def get_run(run_id: str):
    """Get details for a specific fleet run."""
    try:
        from synapsis.database.fleet_operations import get_fleet_run as db_get_run
        run = await db_get_run(run_id)
        if not run:
            raise HTTPException(404, f"Run '{run_id}' not found")
        return {"status": "ok", "run": _row_to_dict(run)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get run %s: %s", run_id, e)
        raise HTTPException(500, f"Failed to get run: {e}")

@router.get("/{fleet_id}")
async def get_fleet(fleet_id: str):
    """Get fleet details including its agents."""
    try:
        from synapsis.database.fleet_operations import list_fleet_agents, list_fleet_runs
        fleet = await _require_fleet(fleet_id)
        agents = await list_fleet_agents(fleet_id)
        runs = await list_fleet_runs(fleet_id)
        return {"status": "ok", "fleet": _row_to_dict(fleet), "agents": _rows_to_list(agents), "runs": _rows_to_list(runs)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to get fleet: {e}")

@router.patch("/{fleet_id}")
async def update_fleet(fleet_id: str, payload: FleetUpdate):
    """Update fleet metadata."""
    try:
        from synapsis.database.fleet_operations import update_fleet as db_update_fleet
        await _require_fleet(fleet_id)
        updated = await db_update_fleet(
            fleet_id, name=payload.name, description=payload.description,
            metadata=payload.metadata,
        )
        return {"status": "ok", "fleet": _row_to_dict(updated)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to update fleet: {e}")

@router.delete("/{fleet_id}")
async def archive_fleet(fleet_id: str):
    """Archive (soft-delete) a fleet."""
    try:
        from synapsis.database.fleet_operations import delete_fleet as db_archive_fleet
        await _require_fleet(fleet_id)
        await db_archive_fleet(fleet_id)
        return {"status": "ok", "id": fleet_id, "archived": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to archive fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to archive fleet: {e}")


# ---------------------------------------------------------------------------
# Fleet agents
# ---------------------------------------------------------------------------

@router.get("/{fleet_id}/agents")
async def list_agents(fleet_id: str):
    """List all agents in a fleet."""
    try:
        from synapsis.database.fleet_operations import list_fleet_agents
        agents = await list_fleet_agents(fleet_id)
        return {"status": "ok", "agents": _rows_to_list(agents)}
    except Exception as e:
        logger.exception("Failed to list agents for fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to list agents: {e}")

@router.get("/{fleet_id}/agents/{agent_id}")
async def get_agent(fleet_id: str, agent_id: str):
    """Get details and messages for a specific agent in a fleet."""
    try:
        from synapsis.database.fleet_operations import get_fleet_agent, get_agent_messages as db_get_msgs
        agent = await get_fleet_agent(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent '{agent_id}' not found in fleet '{fleet_id}'")
        messages = await db_get_msgs(agent_id)
        return {"status": "ok", "agent": _row_to_dict(agent), "messages": _rows_to_list(messages)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get agent %s: %s", agent_id, e)
        raise HTTPException(500, f"Failed to get agent: {e}")


# ---------------------------------------------------------------------------
# Fleet operations (async -- return immediately, run in background)
# ---------------------------------------------------------------------------

@router.post("/{fleet_id}/spawn")
async def spawn_agents(fleet_id: str, payload: SpawnRequest):
    """Spawn agents in a fleet. Starts a batch run in the background."""
    try:
        from synapsis.database.fleet_operations import create_fleet_agents, create_fleet_run
        from synapsis.services.fleet_manager import fleet_manager
        await _require_fleet(fleet_id)

        agents_created = await create_fleet_agents(fleet_id, payload.agents)
        agent_ids = [a["agent_id"] for a in agents_created]
        run = await create_fleet_run(
            fleet_id=fleet_id,
            run_type="spawn",
            agent_ids=agent_ids,
            concurrency=payload.concurrency,
        )
        run_id = run["run_id"]

        # Build agents_and_tasks list for run_batch
        agents_and_tasks = []
        for agent in agents_created:
            agents_and_tasks.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "system_prompt": agent.get("system_prompt", ""),
                "task": agent.get("system_prompt", "You are ready."),
            })

        async def _run():
            try:
                await fleet_manager.run_batch(fleet_id, run_id, agents_and_tasks, payload.concurrency)
            except Exception as exc:
                logger.exception("Fleet batch run %s failed: %s", run_id, exc)

        asyncio.create_task(_run())
        return {"status": "ok", "run_id": run_id, "agents_created": len(agents_created), "agent_ids": agent_ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to spawn agents in fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to spawn agents: {e}")

@router.post("/{fleet_id}/broadcast")
async def broadcast_message(fleet_id: str, payload: BroadcastRequest):
    """Broadcast a message to all agents in a fleet. Runs in background."""
    if not payload.message or not payload.message.strip():
        raise HTTPException(400, "Message is required")
    try:
        from synapsis.services.fleet_manager import fleet_manager
        await _require_fleet(fleet_id)

        async def _run():
            try:
                await fleet_manager.broadcast(fleet_id, payload.message.strip())
            except Exception as exc:
                logger.exception("Fleet broadcast failed: %s", exc)

        asyncio.create_task(_run())
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to broadcast in fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to broadcast: {e}")

@router.post("/{fleet_id}/mediate")
async def mediate_agents(fleet_id: str, payload: MediateRequest):
    """Start mediation between two agents. Runs in background."""
    try:
        from synapsis.services.fleet_manager import fleet_manager
        await _require_fleet(fleet_id)

        async def _run():
            try:
                await fleet_manager.mediate(payload.agent_a, payload.agent_b, payload.topic)
            except Exception as exc:
                logger.exception("Fleet mediation failed: %s", exc)

        asyncio.create_task(_run())
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to start mediation in fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to start mediation: {e}")


# ---------------------------------------------------------------------------
# Fleet runs
# ---------------------------------------------------------------------------

@router.get("/{fleet_id}/runs")
async def list_runs(fleet_id: str):
    """List all runs for a fleet."""
    try:
        from synapsis.database.fleet_operations import list_fleet_runs as db_list_runs
        runs = await db_list_runs(fleet_id)
        return {"status": "ok", "runs": _rows_to_list(runs)}
    except Exception as e:
        logger.exception("Failed to list runs for fleet %s: %s", fleet_id, e)
        raise HTTPException(500, f"Failed to list runs: {e}")
