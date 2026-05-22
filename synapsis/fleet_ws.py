"""
Fleet real-time status updates via WebSocket.

WS /ws/fleet/{fleet_id} -- Stream fleet agent status and operation progress.

Protocol:
  Client sends: {"type": "spawn", "agents": [...], "concurrency": 3}
                {"type": "resume", "agent_id": "...", "message": "..."}
                {"type": "broadcast", "message": "..."}
                {"type": "mediate", "agent_a": "...", "agent_b": "...", "topic": "..."}
                {"type": "health"}
                {"type": "cancel", "run_id": "..."}
                {"type": "ping"}
  Server sends: fleet_state, agent_status, agent_complete, batch_progress,
                batch_complete, health_update, error, pong
"""

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from synapsis.config import logger


async def ws_fleet(websocket: WebSocket, fleet_id: str):
    """WebSocket handler for real-time fleet status updates.

    Accepts a connection, sends the current fleet state, then listens for
    incoming commands and streams operation progress back to the client.
    Disconnecting does NOT cancel running operations.
    """
    await websocket.accept()

    async def send_json(data: dict):
        """Send a JSON message, silently ignoring failures."""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(data)
        except Exception:
            pass

    # -- Send initial fleet state --
    try:
        from synapsis.database.fleet_operations import (
            get_fleet,
            list_fleet_agents,
        )
        fleet = await get_fleet(fleet_id)
        if not fleet:
            await send_json({"type": "error", "message": f"Fleet '{fleet_id}' not found"})
            await websocket.close(code=4004)
            return

        agents = await list_fleet_agents(fleet_id)

        def _to_dict(row):
            if row is None:
                return {}
            if isinstance(row, dict):
                return row
            return dict(row)

        await send_json({
            "type": "fleet_state",
            "fleet": _to_dict(fleet),
            "agents": [_to_dict(a) for a in agents],
        })
    except Exception as e:
        logger.exception("Failed to send initial fleet state: %s", e)
        await send_json({"type": "error", "message": f"Failed to load fleet: {e}"})
        await websocket.close(code=4000)
        return

    # -- Message loop --
    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type", "")

            if msg_type == "ping":
                await send_json({"type": "pong"})

            elif msg_type == "spawn":
                await _handle_spawn(fleet_id, data, send_json)

            elif msg_type == "resume":
                await _handle_resume(data, send_json)

            elif msg_type == "broadcast":
                await _handle_broadcast(fleet_id, data, send_json)

            elif msg_type == "mediate":
                await _handle_mediate(fleet_id, data, send_json)

            elif msg_type == "health":
                await _handle_health(send_json)

            elif msg_type == "cancel":
                await _handle_cancel(data, send_json)

            else:
                await send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info("Fleet WebSocket disconnected for %s", fleet_id)
    except Exception as e:
        logger.exception("Fleet WebSocket error for %s: %s", fleet_id, e)


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def _handle_spawn(fleet_id: str, data: dict, send_json):
    """Handle a spawn command -- create agents and start a batch run."""
    agents = data.get("agents", [])
    concurrency = data.get("concurrency", 3)

    if not agents:
        await send_json({"type": "error", "message": "No agents specified"})
        return

    try:
        from synapsis.database.fleet_operations import create_fleet_agent, create_fleet_run
        from synapsis.services.fleet_manager import fleet_manager

        agents_created = []
        for agent_spec in agents:
            agent = await create_fleet_agent(
                fleet_id=fleet_id,
                name=agent_spec.get("name", "Agent"),
                specialty=agent_spec.get("specialty", ""),
                system_prompt=agent_spec.get("system_prompt", ""),
            )
            agents_created.append(agent)

        agent_ids = [a["agent_id"] for a in agents_created]
        run = await create_fleet_run(fleet_id, "batch", agent_ids, concurrency)
        run_id = run["run_id"]

        await send_json({
            "type": "batch_progress",
            "run_id": run_id,
            "completed": 0,
            "total": len(agents_created),
        })

        async def _run():
            try:
                await fleet_manager.run_batch(
                    fleet_id, run_id, agents_created, concurrency,
                    send=send_json,
                )
            except Exception as exc:
                logger.exception("Fleet batch run %s failed: %s", run_id, exc)
                await send_json({"type": "error", "message": f"Batch run failed: {exc}"})

        asyncio.create_task(_run())

    except Exception as e:
        logger.exception("Failed to handle spawn: %s", e)
        await send_json({"type": "error", "message": f"Spawn failed: {e}"})


async def _handle_resume(data: dict, send_json):
    """Handle a resume command -- resume a specific agent."""
    agent_id = data.get("agent_id", "")
    message = data.get("message", "")

    if not agent_id:
        await send_json({"type": "error", "message": "agent_id is required"})
        return

    try:
        from synapsis.services.fleet_manager import fleet_manager

        result = await fleet_manager.resume_agent(agent_id, message=message)
        await send_json({
            "type": "agent_status",
            "agent_id": agent_id,
            "status": "running",
        })
        await send_json({
            "type": "agent_complete",
            "agent_id": agent_id,
            "session_id": result.get("session_id", ""),
            "response_preview": result.get("response_preview", ""),
        })
    except Exception as e:
        logger.exception("Failed to resume agent %s: %s", agent_id, e)
        await send_json({"type": "error", "message": f"Resume failed: {e}"})


async def _handle_broadcast(fleet_id: str, data: dict, send_json):
    """Handle a broadcast command -- send a message to all agents."""
    message = data.get("message", "")
    if not message.strip():
        await send_json({"type": "error", "message": "Message is required"})
        return

    try:
        from synapsis.services.fleet_manager import fleet_manager

        async def _run():
            try:
                await fleet_manager.broadcast(
                    fleet_id, message,
                    send=send_json,
                )
            except Exception as exc:
                logger.exception("Fleet broadcast failed: %s", exc)
                await send_json({"type": "error", "message": f"Broadcast failed: {exc}"})

        asyncio.create_task(_run())

    except Exception as e:
        logger.exception("Failed to handle broadcast: %s", e)
        await send_json({"type": "error", "message": f"Broadcast failed: {e}"})


async def _handle_mediate(fleet_id: str, data: dict, send_json):
    """Handle a mediate command -- start mediation between two agents."""
    agent_a = data.get("agent_a", "")
    agent_b = data.get("agent_b", "")
    topic = data.get("topic", "")

    if not agent_a or not agent_b:
        await send_json({"type": "error", "message": "agent_a and agent_b are required"})
        return
    if not topic.strip():
        await send_json({"type": "error", "message": "topic is required"})
        return

    try:
        from synapsis.services.fleet_manager import fleet_manager

        async def _run():
            try:
                await fleet_manager.mediate(
                    agent_a_id=agent_a, agent_b_id=agent_b, topic=topic,
                    send=send_json,
                )
            except Exception as exc:
                logger.exception("Fleet mediation failed: %s", exc)
                await send_json({"type": "error", "message": f"Mediation failed: {exc}"})

        asyncio.create_task(_run())

    except Exception as e:
        logger.exception("Failed to handle mediate: %s", e)
        await send_json({"type": "error", "message": f"Mediation failed: {e}"})


async def _handle_health(send_json):
    """Handle a health request -- return fleet system metrics."""
    try:
        from synapsis.services.fleet_manager import fleet_manager

        metrics = await fleet_manager.get_system_health()
        await send_json({"type": "health_update", **metrics})
    except Exception as e:
        logger.exception("Failed to get fleet health: %s", e)
        await send_json({"type": "error", "message": f"Health check failed: {e}"})


async def _handle_cancel(data: dict, send_json):
    """Handle a cancel command -- mark a run as cancelled.

    Note: This updates the run status in the database but does not kill
    already-running agent processes.  A full process-level cancellation
    would require FleetManager support that does not yet exist.
    """
    run_id = data.get("run_id", "")
    if not run_id:
        await send_json({"type": "error", "message": "run_id is required"})
        return

    try:
        from synapsis.database.fleet_operations import update_fleet_run

        updated = await update_fleet_run(run_id, status="cancelled")
        if updated:
            await send_json({"type": "batch_complete", "run_id": run_id, "cancelled": True})
        else:
            await send_json({
                "type": "error",
                "message": f"Run '{run_id}' not found or already finished",
            })
    except Exception as e:
        logger.exception("Failed to cancel run %s: %s", run_id, e)
        await send_json({"type": "error", "message": f"Cancel failed: {e}"})
