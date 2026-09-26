"""
Agent loader -- the specialist roster handed to the SDK's ``agents=`` option.

Security note (2026-09-26, review L1-06 / L3-05 / L7-03): this used to merge
every ``is_active`` row of the ``agents`` table into EVERY user's orchestrator
roster and system prompt. Any signed-in user could therefore create an agent
("route every PRMS question here", "ignore the counting rules") that steered
all other users' answers. The IA app now uses the builtin specialists only;
custom agent rows stay in the database as inert records (their write routes
are administrator-only) and are never injected into a chat.
"""

from claude_agent_sdk import AgentDefinition

from synapsis.agents.definitions import SUBAGENTS


def current_agent_model(model: str | None) -> str:
    """Resolve stored legacy tier aliases without rewriting users' records."""
    return {"sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}.get(model or "sonnet", model)


async def load_all_agents() -> dict[str, AgentDefinition]:
    """Return the builtin specialist roster (a fresh dict each call).

    Kept async and under its historical name so every caller
    (``agent_options``, the persona picker) is unchanged.
    """
    return dict(SUBAGENTS)
