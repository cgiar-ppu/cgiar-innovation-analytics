"""Shared agent creation and ID generation logic.

Centralises the agent ID derivation and INSERT SQL that previously appeared
in routes/agents.py (create_agent, clone_agent) and tools/agents.py
(agent_create).  Callers should use these functions instead of duplicating
the normalisation and persistence logic.
"""

import json
import time
import uuid

from synapsis.agents import SUBAGENTS
from synapsis.constants import DEFAULT_AGENT_COLOR
from synapsis.database import get_db


def generate_agent_id(name: str) -> str:
    """Generate a normalised agent ID from a display name.

    Converts to lowercase, replaces spaces and hyphens with underscores,
    strips non-alphanumeric characters (except underscores), and falls
    back to a UUID-based ID if the result is empty.

    Args:
        name: The human-readable agent name.

    Returns:
        A snake_case identifier string.
    """
    agent_id = name.lower().replace(" ", "_").replace("-", "_")
    agent_id = "".join(c for c in agent_id if c.isalnum() or c == "_")
    if not agent_id:
        agent_id = f"custom_{str(uuid.uuid4())[:8]}"
    return agent_id


async def create_agent_record(
    db,
    agent_id: str,
    name: str,
    description: str,
    system_prompt: str,
    tools: list,
    model: str = "sonnet",
    color: str = DEFAULT_AGENT_COLOR,
    parent_agent: str = "",
) -> dict:
    """Insert a new agent record into the database.

    Handles duplicate ID detection by appending a short UUID suffix when
    a collision is found.

    Args:
        db:            An open aiosqlite connection (caller manages the
                       context manager / transaction).
        agent_id:      The desired agent identifier.
        name:          Human-readable display name.
        description:   Short description of the agent's purpose.
        system_prompt: The full system prompt for this agent.
        tools:         List of tool name strings.
        model:         Model tier (default ``"sonnet"``).
        color:         CSS colour string for the UI card.
        parent_agent:  ID of the agent this was cloned from (empty string
                       for original agents).

    Returns:
        A dict representing the newly created agent row, with keys:
        ``id``, ``name``, ``description``, ``system_prompt``, ``tools``,
        ``model``, ``color``, ``type``, ``is_active``, ``created_at``,
        ``updated_at``, ``parent_agent``, ``version``.
    """
    now = time.time()

    # Check for duplicate ID
    cursor = await db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,))
    if await cursor.fetchone():
        agent_id = f"{agent_id}_{str(uuid.uuid4())[:4]}"

    await db.execute("""
        INSERT INTO agents (id, name, description, system_prompt, tools, model, color,
                            type, is_active, created_at, updated_at, parent_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'custom', 1, ?, ?, ?)
    """, (
        agent_id, name, description, system_prompt,
        json.dumps(tools), model, color,
        now, now, parent_agent,
    ))
    await db.commit()

    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    return dict(row) if row else {"id": agent_id}
