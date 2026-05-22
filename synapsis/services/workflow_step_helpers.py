"""Workflow step helpers -- extracted from workflow_step_runner.py to keep modules concise.

Contains:
- resolve_step_agent: Agent lookup/resolution with fallback to custom agents
- build_step_options: Agent options building for orchestrator and specialist agents
- create_step_log: Step log dict initialization
"""

from typing import Optional

from synapsis.config import logger
from synapsis.agents import SUBAGENTS, load_all_agents, get_agent_display_name
from synapsis.agent_options import build_agent_options, build_generic_agent_options


async def resolve_step_agent(
    agent_id: str,
) -> tuple[bool, Optional[object], str]:
    """Look up the agent definition and derive a display name.

    Returns:
        (is_orchestrator, agent_def, agent_name)
        agent_def is None for orchestrator variants or if the agent was not found.
    """
    is_orchestrator = agent_id in ("orchestrator", "orchestrator_generic")

    agent_def = None
    if not is_orchestrator:
        agent_def = SUBAGENTS.get(agent_id)
        if not agent_def:
            all_agents = await load_all_agents()
            agent_def = all_agents.get(agent_id)

    agent_name = get_agent_display_name(agent_id, agent_def)
    return is_orchestrator, agent_def, agent_name


async def build_step_options(
    is_orchestrator: bool,
    agent_id: str,
    agent_def: Optional[object],
    step_config: dict,
):
    """Build ClaudeAgentOptions for the step.

    Orchestrator variants get the full subagent team (optionally filtered).
    Specialist/custom agents get the standard options with their own prompt.
    """
    if is_orchestrator:
        if agent_id == "orchestrator_generic":
            opts = await build_generic_agent_options()
        else:
            opts = await build_agent_options()
        extra = step_config.get("extra_instructions", "")
        if extra:
            opts.system_prompt += f"\n\n## Additional Instructions for This Step\n{extra}"
        sub_agents = step_config.get("sub_agents")
        if sub_agents and opts.agents:
            opts.agents = {k: v for k, v in opts.agents.items() if k in sub_agents}
    else:
        opts = await build_agent_options()
        if agent_def:
            opts.system_prompt = agent_def.prompt
        # Inject extra instructions for specialist/custom agents too
        extra = step_config.get("extra_instructions", "")
        if extra:
            opts.system_prompt += f"\n\n## Additional Instructions for This Step\n{extra}"

    return opts


def create_step_log(
    step_idx: int,
    agent_id: str,
    agent_name: str,
    is_orchestrator: bool,
    opts,
) -> dict:
    """Build the initial step log dict with pre-execution metadata."""
    step_system_prompt = opts.system_prompt or ""
    return {
        "step_index": step_idx,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "agent_type": (
            "orchestrator" if is_orchestrator else
            ("specialist" if agent_id in SUBAGENTS else "custom")
        ),
        "system_prompt": step_system_prompt,
        "system_prompt_length": len(step_system_prompt),
        "model": opts.model or "",
        "allowed_tools": list(opts.allowed_tools) if opts.allowed_tools else [],
        "subagents": list(opts.agents.keys()) if opts.agents else None,
        "input_prompt": None,
        "input_prompt_length": None,
        "output_text": None,
        "output_text_length": None,
        "started_at": None,
        "completed_at": None,
        "duration_s": None,
        "messages": [],
        "tool_calls_count": 0,
        "estimated_cost_usd": None,
        "turns": None,
        "session_id": None,
        "error": None,
    }
