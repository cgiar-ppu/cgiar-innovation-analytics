"""
Agent management MCP tools — create, list, and update custom agents.

Provides three tools the orchestrator can call:
- agent_create: Create a new custom agent from within a conversation
- agent_list:   List all available agents (builtin + custom)
- agent_update: Update a custom agent's configuration
"""

import json
import time
from typing import Any

from claude_agent_sdk import tool
from synapsis.database import get_db
from synapsis.constants import AVAILABLE_TOOLS
from synapsis.services.agent_service import generate_agent_id, create_agent_record
from synapsis.utils.responses import error_response, success_response
from synapsis.utils.db_helpers import safe_json_loads
from synapsis.validators.agents import validate_model, validate_tools, assert_not_builtin


@tool("agent_create", "Create a new custom specialist agent", {
    "name": str,
    "description": str,
    "system_prompt": str,
    "tools": str,
    "model": str,
})
async def agent_create(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new custom agent and persist it to the database.

    The agent becomes immediately available for routing via the Task tool
    in subsequent sessions (or after the current options are refreshed).
    """
    name = args.get("name", "")
    description = args.get("description", "")
    system_prompt = args.get("system_prompt", "")
    tools_str = args.get("tools", "")
    model = args.get("model", "sonnet")

    if not name or not description or not system_prompt:
        return error_response("Error: name, description, and system_prompt are required")

    # Parse tools
    if tools_str:
        try:
            tools_list = json.loads(tools_str) if tools_str.startswith("[") else [t.strip() for t in tools_str.split(",")]
        except json.JSONDecodeError:
            tools_list = [t.strip() for t in tools_str.split(",")]
    else:
        tools_list = list(AVAILABLE_TOOLS)

    # Validate tools
    try:
        validate_tools(tools_list)
    except ValueError as exc:
        return error_response(f"Error: {exc}")

    # Validate model — coerce to default rather than hard-failing
    try:
        validate_model(model)
    except ValueError:
        model = "sonnet"

    # Generate ID from name using the shared utility
    agent_id = generate_agent_id(name)

    async with get_db() as db:
        row = await create_agent_record(
            db,
            agent_id=agent_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            tools=tools_list,
            model=model,
        )
        created_id = row.get("id", agent_id)

    return success_response(f"Agent '{name}' created successfully (id={created_id}). It will be available for routing in the next conversation turn. Tools: {tools_list}, Model: {model}")


@tool("agent_list", "List all available agents (builtin and custom)", {
    "include_prompts": str,
})
async def agent_list(args: dict[str, Any]) -> dict[str, Any]:
    """List all agents — both builtin and custom from the database."""
    include_prompts = args.get("include_prompts", "false").lower() == "true"

    # Import here to avoid circular imports
    from synapsis.agents import SUBAGENTS

    lines = ["## Available Agents\n"]

    # Builtin agents
    lines.append("### Builtin Agents:")
    for agent_id, agent_def in SUBAGENTS.items():
        lines.append(f"- **{agent_id}** [{agent_def.model}]: {agent_def.description}")
        if include_prompts:
            prompt_preview = agent_def.prompt[:200].replace("\n", " ")
            lines.append(f"  Prompt: {prompt_preview}...")

    # Custom agents from DB
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM agents WHERE is_active = 1 ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()

        if rows:
            lines.append("\n### Custom Agents:")
            for row in rows:
                tools = safe_json_loads(row["tools"])
                lines.append(f"- **{row['id']}** [{row['model']}]: {row['description']}")
                lines.append(f"  Tools: {', '.join(tools)}")
                if include_prompts:
                    prompt_preview = row["system_prompt"][:200].replace("\n", " ")
                    lines.append(f"  Prompt: {prompt_preview}...")
        else:
            lines.append("\n_No custom agents created yet._")

    return success_response("\n".join(lines))


@tool("agent_update", "Update a custom agent's configuration", {
    "agent_id": str,
    "name": str,
    "description": str,
    "system_prompt": str,
    "tools": str,
    "model": str,
})
async def agent_update(args: dict[str, Any]) -> dict[str, Any]:
    """Update an existing custom agent. Cannot modify builtin agents."""
    agent_id = args.get("agent_id", "")
    if not agent_id:
        return error_response("Error: agent_id is required")

    # Check it's not a builtin
    from synapsis.agents import SUBAGENTS
    try:
        assert_not_builtin(agent_id, set(SUBAGENTS) | {"orchestrator"}, action="modify")
    except ValueError as exc:
        return error_response(f"Error: {exc}")

    now = time.time()
    updates = ["updated_at = ?", "version = version + 1"]
    params: list = [now]

    if args.get("name"):
        updates.append("name = ?")
        params.append(args["name"])
    if args.get("description"):
        updates.append("description = ?")
        params.append(args["description"])
    if args.get("system_prompt"):
        updates.append("system_prompt = ?")
        params.append(args["system_prompt"])
    if args.get("tools"):
        tools_str = args["tools"]
        try:
            tools_list = json.loads(tools_str) if tools_str.startswith("[") else [t.strip() for t in tools_str.split(",")]
        except json.JSONDecodeError:
            tools_list = [t.strip() for t in tools_str.split(",")]
        updates.append("tools = ?")
        params.append(json.dumps(tools_list))
    if args.get("model"):
        try:
            validate_model(args["model"])
        except ValueError as exc:
            return error_response(f"Error: {exc}")
        updates.append("model = ?")
        params.append(args["model"])

    params.append(agent_id)

    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM agents WHERE id = ? AND is_active = 1", (agent_id,))
        if not await cursor.fetchone():
            return error_response(f"Error: Custom agent '{agent_id}' not found")

        await db.execute(
            f"UPDATE agents SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()

    return success_response(f"Agent '{agent_id}' updated successfully.")
