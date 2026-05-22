"""
Shared agent validation helpers.

Used by both the REST route layer (synapsis/routes/agents.py) and the MCP
tool layer (synapsis/tools/agents.py) so the same rules are enforced in both
places without duplication.
"""

from synapsis.constants import AVAILABLE_TOOLS

_VALID_MODELS = {"sonnet", "opus"}


def validate_model(model: str) -> None:
    """Raise ValueError if *model* is not an accepted value.

    Args:
        model: The model identifier to validate.

    Raises:
        ValueError: When *model* is not ``'sonnet'`` or ``'opus'``.
    """
    if model not in _VALID_MODELS:
        raise ValueError(f"model must be 'sonnet' or 'opus', got '{model}'")


def validate_tools(tools: list) -> None:
    """Raise ValueError if any tool in *tools* is not in AVAILABLE_TOOLS.

    Args:
        tools: List of tool name strings to validate.

    Raises:
        ValueError: When one or more tool names are not recognised.
    """
    invalid = [t for t in tools if t not in AVAILABLE_TOOLS]
    if invalid:
        raise ValueError(
            f"Invalid tools: {invalid}. Allowed: {AVAILABLE_TOOLS}"
        )


def assert_not_builtin(agent_id: str, builtin_ids: set, action: str = "modify") -> None:
    """Raise ValueError when *agent_id* refers to a builtin agent.

    Args:
        agent_id: The agent identifier being acted upon.
        builtin_ids: Set of builtin agent IDs (e.g. ``set(SUBAGENTS) | {"orchestrator"}``).
        action: Human-readable verb used in the error message (default ``"modify"``).

    Raises:
        ValueError: When *agent_id* is found in *builtin_ids*.
    """
    if agent_id in builtin_ids:
        raise ValueError(
            f"Cannot {action} builtin agent '{agent_id}'. Clone it first."
        )
