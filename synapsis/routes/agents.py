"""
Agent browsing, creation, and management API.

- GET    /api/agents              -- List all agents (builtin + custom)
- GET    /api/agents/{agent_id}   -- Get full details for a specific agent
- POST   /api/agents              -- Create a custom agent
- PUT    /api/agents/{agent_id}   -- Update a custom agent
- DELETE /api/agents/{agent_id}   -- Soft-delete a custom agent
- POST   /api/agents/{id}/clone   -- Clone any agent as a new custom agent
- POST   /api/agents/{id}/test    -- Validate an agent's configuration
"""

import json
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from synapsis.agents import SUBAGENTS, AGENT_REGISTRY
from synapsis.database import get_db
from synapsis.constants import ALLOWED_MODELS, DEFAULT_AGENT_COLOR
from synapsis.services.agent_service import generate_agent_id, create_agent_record
from synapsis.utils.db_helpers import fetch_one_or_404, safe_json_loads
from synapsis.validators.agents import validate_model, validate_tools, assert_not_builtin

_BUILTIN_IDS = set(SUBAGENTS) | {"orchestrator"}

router = APIRouter(prefix="/api", tags=["agents"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = []
    model: str = "sonnet"
    color: str = DEFAULT_AGENT_COLOR

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    model: Optional[str] = None
    color: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _orchestrator_to_dict() -> dict:
    """Build the orchestrator API response dict from AGENT_REGISTRY metadata."""
    meta = AGENT_REGISTRY["orchestrator"]
    return {
        "id": "orchestrator",
        "name": meta["name"],
        "description": meta["description"],
        "type": "builtin",
        "status": "active",
        "tools": meta["tools"],
        "model": meta["model"],
        "color": meta["color"],
        "system_prompt": "",
        "tags": meta["tags"],
        "is_active": 1,
        "created_at": None,
        "updated_at": None,
        "parent_agent": "",
        "version": 1,
    }


def _builtin_agent_to_dict(agent_id: str) -> dict:
    """Convert a builtin agent definition to API response dict."""
    agent_def = SUBAGENTS[agent_id]
    meta = AGENT_REGISTRY.get(agent_id, {})
    return {
        "id": agent_id,
        "name": meta.get("name", agent_id.replace("_", " ").title()),
        "description": agent_def.description,
        "type": "builtin",
        "status": "active",
        "tools": agent_def.tools or [],
        "model": agent_def.model or "sonnet",
        "color": meta.get("color", "hsl(200, 70%, 50%)"),
        "system_prompt": agent_def.prompt,
        "tags": meta.get("tags", []),
        "is_active": 1,
        "created_at": None,
        "updated_at": None,
        "parent_agent": "",
        "version": 1,
    }


def _custom_agent_from_row(row) -> dict:
    """Convert a DB row to an agent API response dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "type": "custom",
        "status": "active" if row["is_active"] else "inactive",
        "tools": safe_json_loads(row["tools"]),
        "model": row["model"],
        "color": row["color"],
        "system_prompt": row["system_prompt"],
        "tags": [],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "parent_agent": row["parent_agent"],
        "version": row["version"],
    }


def _build_update_sql(payload: "AgentUpdate") -> tuple[str, list]:
    """Build SET clause and params from non-None AgentUpdate fields.

    Returns (set_clause_str, params_list) ready for interpolation into
    an UPDATE statement.  Always includes updated_at and version bump.
    """
    set_parts = ["updated_at = ?", "version = version + 1"]
    params: list = [time.time()]
    for key in ("name", "description", "system_prompt", "model", "color"):
        val = getattr(payload, key)
        if val is not None:
            set_parts.append(f"{key} = ?")
            params.append(val)
    if payload.tools is not None:
        set_parts.append("tools = ?")
        params.append(json.dumps(payload.tools))
    return ", ".join(set_parts), params


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/agents")
async def list_agents():
    """List all available agents (builtin + custom merged)."""
    agent_list = [_orchestrator_to_dict()]

    for agent_id in SUBAGENTS:
        agent_list.append(_builtin_agent_to_dict(agent_id))

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM agents WHERE is_active = 1 ORDER BY created_at DESC"
        )
        for row in await cursor.fetchall():
            agent_list.append(_custom_agent_from_row(row))

    return {"agents": agent_list}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get full details for a specific agent (builtin or custom)."""
    if agent_id in SUBAGENTS:
        return _builtin_agent_to_dict(agent_id)
    if agent_id == "orchestrator":
        return _orchestrator_to_dict()

    async with get_db() as db:
        row = await fetch_one_or_404(
            db, "SELECT * FROM agents WHERE id = ?",
            (agent_id,), f"Agent '{agent_id}'",
        )
        return _custom_agent_from_row(row)


@router.post("/agents")
async def create_agent(payload: AgentCreate):
    """Create a new custom agent."""
    if not (1 <= len(payload.name) <= 100):
        raise HTTPException(400, "name must be between 1 and 100 characters")
    if not (1 <= len(payload.description) <= 500):
        raise HTTPException(400, "description must be between 1 and 500 characters")
    if not (1 <= len(payload.system_prompt) <= 10000):
        raise HTTPException(400, "system_prompt must be between 1 and 10000 characters")

    try:
        validate_tools(payload.tools)
        validate_model(payload.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    agent_id = generate_agent_id(payload.name)
    if len(agent_id) > 64:
        agent_id = agent_id[:64]
    if agent_id in _BUILTIN_IDS:
        agent_id = f"custom_{agent_id}"

    async with get_db() as db:
        row = await create_agent_record(
            db, agent_id=agent_id, name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            tools=payload.tools, model=payload.model,
            color=payload.color,
        )
        return _custom_agent_from_row(row)


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, payload: AgentUpdate):
    """Update a custom agent. Cannot update builtin agents."""
    try:
        assert_not_builtin(agent_id, _BUILTIN_IDS, action="modify")
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc

    try:
        if payload.tools is not None:
            validate_tools(payload.tools)
        if payload.model is not None:
            validate_model(payload.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    set_clause, params = _build_update_sql(payload)
    params.append(agent_id)

    async with get_db() as db:
        await fetch_one_or_404(
            db, "SELECT id FROM agents WHERE id = ? AND is_active = 1",
            (agent_id,), f"Custom agent '{agent_id}'",
        )
        await db.execute(f"UPDATE agents SET {set_clause} WHERE id = ?", params)
        await db.commit()

        cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        return _custom_agent_from_row(await cursor.fetchone())


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Soft-delete a custom agent. Cannot delete builtin agents."""
    try:
        assert_not_builtin(agent_id, _BUILTIN_IDS, action="delete")
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc

    async with get_db() as db:
        await fetch_one_or_404(
            db, "SELECT id FROM agents WHERE id = ? AND is_active = 1",
            (agent_id,), f"Custom agent '{agent_id}'",
        )
        await db.execute(
            "UPDATE agents SET is_active = 0, updated_at = ? WHERE id = ?",
            (time.time(), agent_id),
        )
        await db.commit()
    return {"status": "deleted", "id": agent_id}


@router.post("/agents/{agent_id}/clone")
async def clone_agent(agent_id: str):
    """Clone any agent (builtin or custom) as a new custom agent."""
    if agent_id in SUBAGENTS:
        agent_def = SUBAGENTS[agent_id]
        meta = AGENT_REGISTRY.get(agent_id, {})
        source = {
            "name": f"{meta.get('name', agent_id.replace('_', ' ').title())} (Copy)",
            "description": agent_def.description,
            "system_prompt": agent_def.prompt,
            "tools": agent_def.tools or [],
            "model": agent_def.model or "sonnet",
            "color": DEFAULT_AGENT_COLOR,
        }
    else:
        async with get_db() as db:
            row = await fetch_one_or_404(
                db, "SELECT * FROM agents WHERE id = ?",
                (agent_id,), f"Agent '{agent_id}'",
            )
            source = {
                "name": f"{row['name']} (Copy)",
                "description": row["description"],
                "system_prompt": row["system_prompt"],
                "tools": safe_json_loads(row["tools"]),
                "model": row["model"],
                "color": row["color"],
            }

    clone_id = f"clone_{agent_id}_{str(uuid.uuid4())[:4]}"
    async with get_db() as db:
        row = await create_agent_record(
            db, agent_id=clone_id, parent_agent=agent_id, **source,
        )
        return _custom_agent_from_row(row)


@router.post("/agents/{agent_id}/test")
async def test_agent(agent_id: str, body: dict = {}):
    """Validate an agent's configuration without running the full SDK."""
    agent = await get_agent(agent_id)
    issues: list[str] = []

    model = agent.get("model") or ""
    system_prompt = agent.get("system_prompt") or ""
    tools = agent.get("tools")

    if model not in ALLOWED_MODELS:
        issues.append(
            f"model '{model}' is not one of the allowed values: {sorted(ALLOWED_MODELS)}"
        )
    if not system_prompt.strip():
        issues.append("system_prompt is empty")
    if not isinstance(tools, list):
        issues.append("tools is not a valid array")
    else:
        try:
            json.dumps(tools)
        except (TypeError, ValueError) as exc:
            issues.append(f"tools is not JSON-serialisable: {exc}")

    return {
        "valid": len(issues) == 0,
        "agent_id": agent_id,
        "issues": issues,
        "config": {
            "model": model,
            "tools": tools if isinstance(tools, list) else [],
            "type": agent.get("type"),
            "system_prompt_length": len(system_prompt),
        },
    }
