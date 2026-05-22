"""Fleet management MCP tools -- create, spawn, resume, mediate, and inspect fleets.

Provides seven tools the orchestrator can call:
- fleet_create:     Create a new fleet grouping
- fleet_spawn:      Spawn agents in a fleet and run initial tasks
- fleet_resume:     Resume a specific agent or broadcast to all agents
- fleet_mediate:    Facilitate a conversation between two agents
- fleet_status:     Get fleet status, agent statuses, and system health
- fleet_inspect:    Get the message history of a specific agent
- fleet_initialize: Two-phase initialization -- analyze content then create expert agents
"""

import json
import time
from typing import Any

from claude_agent_sdk import tool
from synapsis.utils.responses import error_response, success_response
from synapsis.database.fleet_schema import init_fleet_db
from synapsis.database.fleet_operations import (
    create_fleet, get_fleet, list_fleets, update_fleet,
    create_fleet_agent, get_fleet_agent, list_fleet_agents,
    create_fleet_run, get_fleet_run, list_fleet_runs,
    get_agent_messages, get_health_history,
)
from synapsis.services.fleet_manager import fleet_manager

# Flag to ensure schema is initialized before first use
_schema_initialized = False


async def _ensure_schema():
    """Lazily initialize the fleet database schema on first tool call."""
    global _schema_initialized
    if not _schema_initialized:
        await init_fleet_db()
        _schema_initialized = True


# ---------------------------------------------------------------------------
# fleet_create
# ---------------------------------------------------------------------------

@tool("fleet_create", "Create a new fleet of Claude Code agents", {
    "name": str,
    "description": str,
    "project_path": str,
    "tags": str,
})
async def fleet_create(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new fleet with a name, description, project path, and tags."""
    await _ensure_schema()

    name = args.get("name", "").strip()
    if not name:
        return error_response("Error: 'name' is required to create a fleet.")

    description = args.get("description", "")
    project_path = args.get("project_path", "")

    # Parse tags from comma-separated or JSON string
    tags_raw = args.get("tags", "")
    if tags_raw:
        try:
            tags = json.loads(tags_raw) if tags_raw.startswith("[") else [
                t.strip() for t in tags_raw.split(",") if t.strip()
            ]
        except json.JSONDecodeError:
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        tags = []

    fleet = await create_fleet(
        name=name, description=description,
        project_path=project_path, tags=tags,
    )

    lines = [
        f"## Fleet Created: {name}",
        f"- **Fleet ID:** `{fleet['fleet_id']}`",
        f"- **Description:** {description or '(none)'}",
        f"- **Project Path:** {project_path or '(none)'}",
        f"- **Tags:** {', '.join(tags) if tags else '(none)'}",
        f"- **Status:** active",
        "",
        "Use `fleet_spawn` to add agents to this fleet.",
    ]
    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_spawn
# ---------------------------------------------------------------------------

@tool("fleet_spawn", "Spawn agents in a fleet and run initial tasks", {
    "fleet_id": str,
    "agents": str,
    "concurrency": str,
})
async def fleet_spawn(args: dict[str, Any]) -> dict[str, Any]:
    """Spawn agents in a fleet from a JSON manifest.

    ``agents`` should be a JSON string of:
    ``[{"name": "...", "specialty": "...", "system_prompt": "...", "task": "..."}, ...]``
    """
    await _ensure_schema()

    fleet_id = args.get("fleet_id", "").strip()
    if not fleet_id:
        return error_response("Error: 'fleet_id' is required.")

    fleet = await get_fleet(fleet_id)
    if not fleet:
        return error_response(f"Error: Fleet '{fleet_id}' not found.")

    agents_raw = args.get("agents", "")
    if not agents_raw:
        return error_response("Error: 'agents' JSON manifest is required.")

    try:
        agent_specs = json.loads(agents_raw)
    except json.JSONDecodeError as e:
        return error_response(f"Error: Invalid JSON in 'agents': {e}")

    if not isinstance(agent_specs, list) or not agent_specs:
        return error_response("Error: 'agents' must be a non-empty JSON array.")

    concurrency = int(args.get("concurrency", "3"))

    # Create agent records in the DB
    agents_and_tasks = []
    created_ids = []
    for spec in agent_specs:
        agent = await create_fleet_agent(
            fleet_id=fleet_id,
            name=spec.get("name", "Agent"),
            specialty=spec.get("specialty", ""),
            system_prompt=spec.get("system_prompt", ""),
        )
        agents_and_tasks.append({
            "agent_id": agent["agent_id"],
            "task": spec.get("task", ""),
            "system_prompt": spec.get("system_prompt", ""),
        })
        created_ids.append(agent["agent_id"])

    # Create a run record
    run = await create_fleet_run(
        fleet_id, "spawn", created_ids, concurrency,
        f"Spawning {len(agent_specs)} agents",
    )

    # Execute batch (non-blocking from the tool's perspective is not possible
    # since the orchestrator needs results; we run synchronously)
    results = await fleet_manager.run_batch(
        fleet_id, run["run_id"], agents_and_tasks, concurrency,
    )

    # Format output
    lines = [
        f"## Fleet Spawn Complete: {fleet['name']}",
        f"- **Run ID:** `{run['run_id']}`",
        f"- **Agents spawned:** {len(results)}",
        f"- **Concurrency:** {concurrency}",
        "",
    ]
    for r in results:
        aid = r.get("agent_id", "?")
        if "error" in r:
            lines.append(f"- `{aid}`: ERROR -- {r['error'][:200]}")
        else:
            sid = r.get("session_id", "(none)")
            resp_preview = r.get("response", "")[:150].replace("\n", " ")
            lines.append(f"- `{aid}` (session: `{sid}`): {resp_preview}...")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_resume
# ---------------------------------------------------------------------------

@tool("fleet_resume", "Resume a specific agent or broadcast to all agents in a fleet", {
    "agent_id": str,
    "fleet_id": str,
    "message": str,
    "concurrency": str,
})
async def fleet_resume(args: dict[str, Any]) -> dict[str, Any]:
    """Resume a single agent by agent_id, or broadcast to all agents in a fleet."""
    await _ensure_schema()

    message = args.get("message", "").strip()
    if not message:
        return error_response("Error: 'message' is required.")

    agent_id = args.get("agent_id", "").strip()
    fleet_id = args.get("fleet_id", "").strip()

    if not agent_id and not fleet_id:
        return error_response("Error: Provide either 'agent_id' or 'fleet_id'.")

    # Single agent resume
    if agent_id:
        result = await fleet_manager.resume_agent(agent_id, message)

        if "error" in result:
            return error_response(f"Resume failed: {result['error']}")

        resp_preview = result.get("response", "")[:2000]
        lines = [
            f"## Agent Resumed: `{agent_id}`",
            f"- **Session:** `{result.get('session_id', '(none)')}`",
            "",
            "### Response",
            resp_preview,
        ]
        return success_response("\n".join(lines))

    # Broadcast to entire fleet
    concurrency = int(args.get("concurrency", "3"))
    results = await fleet_manager.broadcast(fleet_id, message, concurrency=concurrency)

    lines = [
        f"## Broadcast Complete: Fleet `{fleet_id}`",
        f"- **Message:** {message[:100]}",
        f"- **Agents reached:** {len(results)}",
        "",
    ]
    for r in results:
        aid = r.get("agent_id", "?")
        if "error" in r:
            lines.append(f"- `{aid}`: ERROR -- {r['error'][:200]}")
        else:
            resp_preview = r.get("response", "")[:150].replace("\n", " ")
            lines.append(f"- `{aid}`: {resp_preview}...")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_mediate
# ---------------------------------------------------------------------------

@tool("fleet_mediate", "Facilitate a conversation between two fleet agents", {
    "agent_a_id": str,
    "agent_b_id": str,
    "topic": str,
    "rounds": str,
})
async def fleet_mediate(args: dict[str, Any]) -> dict[str, Any]:
    """Start a mediated conversation between two agents on a given topic."""
    await _ensure_schema()

    agent_a_id = args.get("agent_a_id", "").strip()
    agent_b_id = args.get("agent_b_id", "").strip()
    topic = args.get("topic", "").strip()

    if not agent_a_id or not agent_b_id:
        return error_response("Error: Both 'agent_a_id' and 'agent_b_id' are required.")
    if not topic:
        return error_response("Error: 'topic' is required.")

    rounds = int(args.get("rounds", "2"))

    result = await fleet_manager.mediate(agent_a_id, agent_b_id, topic, rounds)

    lines = [
        f"## Mediation Complete",
        f"- **Topic:** {topic}",
        f"- **Rounds:** {rounds}",
        f"- **Participants:** `{agent_a_id}` and `{agent_b_id}`",
        "",
    ]
    for i, entry in enumerate(result.get("conversation", [])):
        agent = entry.get("agent", "?")
        resp = entry.get("response", "")[:500].replace("\n", " ")
        lines.append(f"### Turn {i + 1} (Agent `{agent}`)")
        lines.append(resp)
        lines.append("")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_status
# ---------------------------------------------------------------------------

@tool("fleet_status", "Get fleet status, agent statuses, and system health", {
    "fleet_id": str,
})
async def fleet_status(args: dict[str, Any]) -> dict[str, Any]:
    """Get status of a specific fleet or all fleets, plus system health."""
    await _ensure_schema()

    fleet_id = args.get("fleet_id", "").strip()
    lines = []

    if fleet_id:
        fleet = await get_fleet(fleet_id)
        if not fleet:
            return error_response(f"Error: Fleet '{fleet_id}' not found.")

        agents = await list_fleet_agents(fleet_id)
        runs = await list_fleet_runs(fleet_id)

        lines.append(f"## Fleet: {fleet.get('name', fleet_id)}")
        lines.append(f"- **ID:** `{fleet_id}`")
        lines.append(f"- **Status:** {fleet.get('status', 'unknown')}")
        lines.append(f"- **Project:** {fleet.get('project_path', '(none)')}")
        lines.append(f"- **Agents:** {len(agents)}")
        lines.append(f"- **Runs:** {len(runs)}")
        lines.append("")

        if agents:
            lines.append("### Agents")
            for a in agents:
                sid = a.get("claude_session_id", "")
                session_marker = f" (session: `{sid[:8]}...`)" if sid else " (no session)"
                lines.append(
                    f"- `{a['agent_id']}` **{a.get('name', '?')}** "
                    f"[{a.get('status', '?')}] turns={a.get('turn_count', 0)}"
                    f"{session_marker}"
                )
                if a.get("specialty"):
                    lines.append(f"  Specialty: {a['specialty']}")
    else:
        fleets = await list_fleets()
        lines.append("## All Fleets")
        if not fleets:
            lines.append("_No fleets created yet._")
        else:
            for f in fleets:
                agents = await list_fleet_agents(f["fleet_id"])
                lines.append(
                    f"- `{f['fleet_id']}` **{f.get('name', '?')}** "
                    f"[{f.get('status', '?')}] -- {len(agents)} agents"
                )

    # System health
    lines.append("")
    lines.append("### System Health")
    health = await fleet_manager.get_system_health()
    if health.get("error"):
        lines.append(f"- {health['error']}")
    else:
        lines.append(f"- **RAM:** {health['ram_available_gb']:.1f} GB free / {health['ram_total_gb']:.1f} GB total ({health['ram_used_pct']:.0f}% used)")
        lines.append(f"- **CPU:** {health['cpu_pct']:.0f}%")
        lines.append(f"- **Active agents:** {health['active_agents']}")
        lines.append(f"- **Claude processes:** {health['claude_processes']}")
        lines.append(f"- **Can spawn more:** {'Yes' if health.get('can_spawn_more') else 'No'}")
        lines.append(f"- **Recommended concurrency:** {health.get('recommended_concurrency', '?')}")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_inspect
# ---------------------------------------------------------------------------

@tool("fleet_inspect", "Get the message history of a specific fleet agent", {
    "agent_id": str,
    "limit": str,
})
async def fleet_inspect(args: dict[str, Any]) -> dict[str, Any]:
    """Inspect an agent's conversation history and metadata."""
    await _ensure_schema()

    agent_id = args.get("agent_id", "").strip()
    if not agent_id:
        return error_response("Error: 'agent_id' is required.")

    agent = await get_fleet_agent(agent_id)
    if not agent:
        return error_response(f"Error: Agent '{agent_id}' not found.")

    limit = int(args.get("limit", "50"))
    messages = await get_agent_messages(agent_id, limit=limit)

    lines = [
        f"## Agent: {agent.get('name', agent_id)}",
        f"- **ID:** `{agent_id}`",
        f"- **Fleet:** `{agent.get('fleet_id', '?')}`",
        f"- **Status:** {agent.get('status', '?')}",
        f"- **Specialty:** {agent.get('specialty', '(none)')}",
        f"- **Session:** `{agent.get('claude_session_id', '(none)')}`",
        f"- **Turns:** {agent.get('turn_count', 0)}",
        f"- **Worker:** {agent.get('worker_node', 'local')}",
    ]

    if agent.get("context_summary"):
        lines.append(f"- **Context Summary:** {agent['context_summary'][:300]}")
    if agent.get("result"):
        lines.append(f"- **Last Result:** {agent['result'][:300]}")
    if agent.get("error_message"):
        lines.append(f"- **Last Error:** {agent['error_message'][:300]}")

    lines.append("")
    lines.append(f"### Message History ({len(messages)} messages)")

    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:500].replace("\n", " ")
        turn = msg.get("turn_number", 0)
        lines.append(f"**[Turn {turn}] {role}:** {content}")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# fleet_initialize
# ---------------------------------------------------------------------------

@tool("fleet_initialize", "Initialize expert agents by analyzing content first", {
    "fleet_id": str,
    "targets": str,
    "concurrency": str,
})
async def fleet_initialize(args: dict[str, Any]) -> dict[str, Any]:
    """Two-phase initialization: analyze content then create expert agents.

    ``targets`` should be a JSON array of:
    ``[{"name": "...", "target": "...", "context": "..."}, ...]``

    Each target is processed in two phases:
    1. A temporary initializer agent analyzes the content and produces a
       blueprint (tailored system prompt, specialty, context summary).
    2. The actual expert agent is created with the tailored system prompt
       and spawned with a verification task.
    """
    await _ensure_schema()

    fleet_id = args.get("fleet_id", "").strip()
    if not fleet_id:
        return error_response("Error: 'fleet_id' is required.")

    fleet = await get_fleet(fleet_id)
    if not fleet:
        return error_response(f"Error: Fleet '{fleet_id}' not found.")

    targets_raw = args.get("targets", "")
    if not targets_raw:
        return error_response("Error: 'targets' JSON array is required.")

    try:
        targets = json.loads(targets_raw)
    except json.JSONDecodeError as e:
        return error_response(f"Error: Invalid JSON in 'targets': {e}")

    if not isinstance(targets, list) or not targets:
        return error_response(
            "Error: 'targets' must be a non-empty JSON array of "
            '{"name": "...", "target": "...", "context": "..."}.'
        )

    concurrency = int(args.get("concurrency", "3"))

    results = await fleet_manager.batch_initialize(
        fleet_id=fleet_id,
        targets=targets,
        concurrency=concurrency,
    )

    # Format output
    lines = [
        f"## Fleet Initialization Complete: {fleet.get('name', fleet_id)}",
        f"- **Fleet ID:** `{fleet_id}`",
        f"- **Targets processed:** {len(results)}",
        f"- **Concurrency:** {concurrency}",
        "",
    ]

    succeeded = 0
    failed = 0
    for r in results:
        name = r.get("agent_name", "?")
        if r.get("error"):
            failed += 1
            lines.append(f"- **{name}**: ERROR -- {r['error'][:200]}")
        else:
            succeeded += 1
            aid = r.get("agent_id", "?")
            specialty = r.get("specialty", "(none)")
            sid = r.get("session_id", "(none)")
            lines.append(f"- **{name}** (`{aid}`, session: `{sid}`)")
            lines.append(f"  Specialty: {specialty}")
            insights = r.get("key_insights", [])
            if insights:
                for insight in insights[:5]:
                    lines.append(f"  - {insight}")

    lines.insert(5, f"- **Succeeded:** {succeeded} | **Failed:** {failed}")

    return success_response("\n".join(lines))
