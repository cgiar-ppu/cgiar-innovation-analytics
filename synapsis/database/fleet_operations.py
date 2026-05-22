"""CRUD operations for all fleet tables.

Provides functions for managing fleets, agents, runs, messages, and health
snapshots in the fleet database (fleet.db).
"""

import json
import time
import uuid
from typing import Any

from synapsis.database.fleet_connection import get_fleet_db


def _row_to_dict(row) -> dict:
    """Convert an aiosqlite.Row to a plain dict, deserializing JSON fields."""
    if not row:
        return {}
    d = dict(row)
    # Deserialize JSON-encoded fields stored as TEXT in SQLite
    for key in ("tags", "config", "agent_ids"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = [] if key in ("tags", "agent_ids") else {}
    return d


def _gen_id() -> str:
    """Generate an 8-character UUID prefix."""
    return str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Fleet CRUD
# ---------------------------------------------------------------------------

async def create_fleet(
    name: str,
    description: str = "",
    project_path: str = "",
    tags: list[str] | None = None,
    chat_session_id: str = "",
    config: dict | None = None,
) -> dict:
    """Create a new fleet and return its record as a dict."""
    fleet_id = _gen_id()
    now = time.time()
    tags_json = json.dumps(tags or [])
    config_json = json.dumps(config or {})

    async with get_fleet_db() as db:
        await db.execute(
            """INSERT INTO fleets
               (fleet_id, name, description, project_path, tags, status,
                created_at, updated_at, chat_session_id, config)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
            (fleet_id, name, description, project_path, tags_json,
             now, now, chat_session_id, config_json),
        )
        await db.commit()

    return {
        "fleet_id": fleet_id, "name": name, "description": description,
        "project_path": project_path, "tags": tags or [], "status": "active",
        "created_at": now, "updated_at": now, "chat_session_id": chat_session_id,
        "config": config or {},
    }


async def get_fleet(fleet_id: str) -> dict | None:
    """Return a single fleet record or None."""
    async with get_fleet_db() as db:
        cursor = await db.execute("SELECT * FROM fleets WHERE fleet_id = ?", (fleet_id,))
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None


async def list_fleets(
    status: str | None = None,
    project_path: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """List fleets with optional filters."""
    query = "SELECT * FROM fleets WHERE 1=1"
    params: list[Any] = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if project_path:
        query += " AND project_path = ?"
        params.append(project_path)

    query += " ORDER BY updated_at DESC"

    async with get_fleet_db() as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    results = [_row_to_dict(r) for r in rows]

    # Client-side tag filter (tags already deserialized by _row_to_dict)
    if tag:
        results = [f for f in results if tag in (f.get("tags") or [])]

    return results


async def update_fleet(fleet_id: str, **kwargs) -> bool:
    """Update fleet fields. Returns True if a row was modified."""
    if not kwargs:
        return False
    kwargs["updated_at"] = time.time()
    columns = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [fleet_id]

    async with get_fleet_db() as db:
        cursor = await db.execute(
            f"UPDATE fleets SET {columns} WHERE fleet_id = ?", values,
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_fleet(fleet_id: str) -> bool:
    """Archive a fleet (soft delete). Returns True if updated."""
    return await update_fleet(fleet_id, status="archived")


# Alias for backward compatibility
archive_fleet = delete_fleet


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

async def create_fleet_agent(
    fleet_id: str,
    name: str,
    specialty: str = "",
    system_prompt: str = "",
    worker_node: str = "local",
) -> dict:
    """Create a new agent in a fleet."""
    agent_id = _gen_id()
    now = time.time()

    async with get_fleet_db() as db:
        await db.execute(
            """INSERT INTO fleet_agents
               (agent_id, fleet_id, name, specialty, system_prompt,
                worker_node, status, turn_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'idle', 0, ?, ?)""",
            (agent_id, fleet_id, name, specialty, system_prompt, worker_node, now, now),
        )
        await db.commit()

    return {
        "agent_id": agent_id, "fleet_id": fleet_id, "name": name,
        "specialty": specialty, "system_prompt": system_prompt,
        "worker_node": worker_node, "status": "idle", "turn_count": 0,
        "created_at": now, "updated_at": now,
    }


async def create_fleet_agents(fleet_id: str, agents: list[dict]) -> list[dict]:
    """Create multiple agents in a fleet. Returns list of created agent dicts."""
    results = []
    for agent_spec in agents:
        agent = await create_fleet_agent(
            fleet_id=fleet_id,
            name=agent_spec.get("name", "Agent"),
            specialty=agent_spec.get("specialty", ""),
            system_prompt=agent_spec.get("system_prompt", ""),
            worker_node=agent_spec.get("worker_node", "local"),
        )
        results.append(agent)
    return results


async def get_fleet_agent(agent_id: str) -> dict | None:
    """Return a single fleet agent record or None."""
    async with get_fleet_db() as db:
        cursor = await db.execute(
            "SELECT * FROM fleet_agents WHERE agent_id = ?", (agent_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None


async def list_fleet_agents(fleet_id: str, status: str | None = None) -> list[dict]:
    """List agents in a fleet with optional status filter."""
    query = "SELECT * FROM fleet_agents WHERE fleet_id = ?"
    params: list[Any] = [fleet_id]

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at ASC"

    async with get_fleet_db() as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    return [_row_to_dict(r) for r in rows]


async def update_fleet_agent(agent_id: str, **kwargs) -> bool:
    """Update agent fields. Returns True if a row was modified."""
    if not kwargs:
        return False
    kwargs["updated_at"] = time.time()
    columns = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [agent_id]

    async with get_fleet_db() as db:
        cursor = await db.execute(
            f"UPDATE fleet_agents SET {columns} WHERE agent_id = ?", values,
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_agent_session(agent_id: str, claude_session_id: str) -> bool:
    """Set the Claude Code session ID for resume capability."""
    return await update_fleet_agent(agent_id, claude_session_id=claude_session_id)


async def update_agent_status(
    agent_id: str,
    status: str,
    result: str | None = None,
    error_message: str | None = None,
) -> bool:
    """Update an agent's status and optionally its result or error."""
    kwargs: dict[str, Any] = {"status": status, "last_active": time.time()}
    if result is not None:
        kwargs["result"] = result
    if error_message is not None:
        kwargs["error_message"] = error_message
    return await update_fleet_agent(agent_id, **kwargs)


async def update_agent_summary(agent_id: str, context_summary: str) -> bool:
    """Update the LLM-generated context summary for an agent."""
    return await update_fleet_agent(agent_id, context_summary=context_summary)


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------

async def create_fleet_run(
    fleet_id: str,
    run_type: str = "batch",
    agent_ids: list[str] | None = None,
    concurrency: int = 3,
    prompt: str = "",
) -> dict:
    """Create a new fleet run record."""
    run_id = _gen_id()
    agent_ids_json = json.dumps(agent_ids or [])

    async with get_fleet_db() as db:
        await db.execute(
            """INSERT INTO fleet_runs
               (run_id, fleet_id, run_type, status, agent_ids, concurrency, prompt)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
            (run_id, fleet_id, run_type, agent_ids_json, concurrency, prompt),
        )
        await db.commit()

    return {
        "run_id": run_id, "fleet_id": fleet_id, "run_type": run_type,
        "status": "pending", "agent_ids": agent_ids or [], "concurrency": concurrency,
        "prompt": prompt,
    }


async def update_fleet_run(run_id: str, **kwargs) -> bool:
    """Update run fields. Returns True if a row was modified."""
    if not kwargs:
        return False
    # Serialize lists/dicts to JSON for storage
    for key in ("agent_ids", "metadata"):
        if key in kwargs and isinstance(kwargs[key], (list, dict)):
            kwargs[key] = json.dumps(kwargs[key])

    columns = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [run_id]

    async with get_fleet_db() as db:
        cursor = await db.execute(
            f"UPDATE fleet_runs SET {columns} WHERE run_id = ?", values,
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_fleet_run(run_id: str) -> dict | None:
    """Return a single fleet run record or None."""
    async with get_fleet_db() as db:
        cursor = await db.execute(
            "SELECT * FROM fleet_runs WHERE run_id = ?", (run_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None


async def list_fleet_runs(fleet_id: str) -> list[dict]:
    """List all runs for a fleet, newest first."""
    async with get_fleet_db() as db:
        cursor = await db.execute(
            "SELECT * FROM fleet_runs WHERE fleet_id = ? ORDER BY started_at DESC",
            (fleet_id,),
        )
        rows = await cursor.fetchall()

    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def save_fleet_message(
    agent_id: str,
    run_id: str,
    role: str,
    content: str,
    turn_number: int = 0,
) -> None:
    """Save a message exchanged with a fleet agent."""
    now = time.time()

    async with get_fleet_db() as db:
        await db.execute(
            """INSERT INTO fleet_messages
               (agent_id, run_id, role, content, turn_number, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, run_id, role, content, turn_number, now),
        )
        await db.commit()


async def get_agent_messages(agent_id: str, limit: int = 50) -> list[dict]:
    """Get recent messages for an agent, oldest first."""
    async with get_fleet_db() as db:
        cursor = await db.execute(
            """SELECT * FROM fleet_messages WHERE agent_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()

    # Return in chronological order
    return [_row_to_dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def save_health_snapshot(
    ram_total: float,
    ram_available: float,
    ram_used_pct: float,
    cpu_pct: float,
    active_agents: int = 0,
    claude_processes: int = 0,
) -> None:
    """Save a system health snapshot."""
    now = time.time()

    async with get_fleet_db() as db:
        await db.execute(
            """INSERT INTO fleet_health
               (timestamp, ram_total_gb, ram_available_gb, ram_used_pct,
                cpu_pct, active_agents, claude_processes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, ram_total, ram_available, ram_used_pct, cpu_pct,
             active_agents, claude_processes),
        )
        await db.commit()


async def get_health_history(limit: int = 60) -> list[dict]:
    """Get recent health snapshots, newest first."""
    async with get_fleet_db() as db:
        cursor = await db.execute(
            "SELECT * FROM fleet_health ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()

    return [_row_to_dict(r) for r in rows]
