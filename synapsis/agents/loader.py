"""
Agent loader -- merges builtin SUBAGENTS with custom agents from the database.

Provides load_all_agents(), which returns a combined dict of AgentDefinition
instances suitable for the SDK's agents= parameter.
"""

import json

import aiosqlite
from claude_agent_sdk import AgentDefinition

from synapsis.agents.definitions import SUBAGENTS, _STANDARD_TOOLS


async def load_all_agents() -> dict[str, AgentDefinition]:
    """Merge builtin SUBAGENTS with custom agents from the database.

    Returns a new dict containing both builtin and custom agents as
    AgentDefinition instances suitable for the SDK's agents= parameter.
    """
    from synapsis.database import get_db

    merged = dict(SUBAGENTS)
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM agents WHERE is_active = 1"
            )
            rows = await cursor.fetchall()
            for row in rows:
                tools = json.loads(row["tools"]) if row["tools"] else _STANDARD_TOOLS
                merged[row["id"]] = AgentDefinition(
                    description=row["description"],
                    prompt=row["system_prompt"],
                    tools=tools,
                    model=row["model"] or "sonnet",
                )
    except (aiosqlite.OperationalError, aiosqlite.DatabaseError):
        pass  # DB not ready yet -- return builtin agents only
    return merged
