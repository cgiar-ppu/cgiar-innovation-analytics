"""
Per-agent stateless query endpoint — talk directly to a specific agent.

- POST /api/agents/{agent_id}/query — Send a message to a specific agent
  without going through the orchestrator. Supports both builtin and custom agents.

This reuses the agent resolution and option-building logic from the workflow
step runner, so any agent that works in a workflow pipeline also works here.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from claude_agent_sdk import (
    query,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from synapsis.config import logger
from synapsis.services.workflow_step_helpers import resolve_step_agent, build_step_options


router = APIRouter(prefix="/api", tags=["agent-query"])


class AgentQueryRequest(BaseModel):
    """POST /api/agents/{agent_id}/query — direct agent query."""
    message: str = Field(..., min_length=1, max_length=50000)
    extra_instructions: Optional[str] = Field(default=None, max_length=5000)


@router.post("/agents/{agent_id}/query")
async def agent_query(agent_id: str, payload: AgentQueryRequest):
    """Send a message directly to a specific agent (bypasses orchestrator).

    This endpoint resolves the agent by ID (builtin or custom), builds
    agent-specific options using the same logic as workflow steps, and
    runs the query directly. No orchestrator overhead.

    The agent has full access to its configured tools (Bash, Read, Write,
    etc.) and can execute code, read files, and interact with the system.

    Args:
        agent_id: The agent identifier (e.g. "data_analysis", "computer_use",
                  or a custom agent ID from the database).
        payload: The query message and optional extra instructions.

    Returns:
        response: Combined text output from the agent
        tool_uses: List of tools the agent invoked
        result: Cost, turns, and duration metadata
        agent_id: The resolved agent ID
        agent_name: Human-readable agent display name
    """
    # Resolve the agent definition
    is_orchestrator, agent_def, agent_name = await resolve_step_agent(agent_id)

    # For orchestrator variants, allow but note it goes through full orchestrator
    if not is_orchestrator and not agent_def:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found. Use GET /api/agents to list available agents.",
        )

    # Build agent-specific options (reuses workflow step logic)
    step_config = {}
    if payload.extra_instructions:
        step_config["extra_instructions"] = payload.extra_instructions

    opts = await build_step_options(is_orchestrator, agent_id, agent_def, step_config)

    # Run the query
    user_msg = payload.message.strip()
    texts: list[str] = []
    tool_uses: list[dict] = []
    result_info: dict = {}

    try:
        async for message in query(prompt=user_msg, options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_uses.append({"tool": block.name, "input": block.input})
            elif isinstance(message, ResultMessage):
                result_info = {
                    "estimated_cost": message.total_cost_usd,
                    "turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                }
    except Exception as exc:
        logger.exception("Agent query failed for %s", agent_id)
        raise HTTPException(
            status_code=500,
            detail=f"Agent query failed: {exc}",
        ) from exc

    return {
        "response": "\n".join(texts),
        "tool_uses": tool_uses,
        "result": result_info,
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
