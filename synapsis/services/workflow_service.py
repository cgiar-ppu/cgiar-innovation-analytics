"""
Workflow business logic — pure/testable functions extracted from route handlers.
"""

from __future__ import annotations

from synapsis.agents import SUBAGENTS


def validate_agent_sequence(agent_sequence: list[str], known_custom_ids: set[str] | None = None) -> list[str]:
    """Validate that every agent ID in a sequence is recognised.

    Built-in orchestrator IDs (``"orchestrator"`` and ``"orchestrator_generic"``)
    are always accepted.  Other IDs must appear in ``SUBAGENTS`` or in the
    optional *known_custom_ids* set (pre-fetched from the database by the
    caller).

    Args:
        agent_sequence: Ordered list of agent identifier strings.
        known_custom_ids: Optional set of custom agent IDs that are active in
            the database.  When ``None``, only built-in agents are accepted.

    Returns:
        The validated *agent_sequence* (unchanged).

    Raises:
        ValueError: If any agent ID is unrecognised.
    """
    builtin = {"orchestrator", "orchestrator_generic"}
    custom = known_custom_ids or set()

    for agent_id in agent_sequence:
        if agent_id in builtin:
            continue
        if agent_id in SUBAGENTS:
            continue
        if agent_id in custom:
            continue
        raise ValueError(f"Unknown agent: {agent_id}")

    return agent_sequence


def build_continuation_context(
    run: dict,
    steps: list[dict],
) -> str:
    """Build a context message for continuing a chat from a workflow run.

    This is a pure function: it accepts the run metadata and step list and
    returns the Markdown context string that will be stored and shown in the
    new chat session.

    Args:
        run: Workflow run metadata dict (must contain ``initial_prompt``,
            ``workflow_name``, and ``total_duration_s``).
        steps: List of step dicts; each should have an ``output_text`` key.

    Returns:
        Formatted Markdown string summarising the workflow output.
    """
    last_step = steps[-1] if steps else None
    last_output = last_step["output_text"] if last_step else "No output available."

    step_label = "agent" if len(steps) == 1 else "agents"
    duration = run.get("total_duration_s") or 0

    return (
        f"## Workflow Context\n\n"
        f"You are continuing a conversation based on the output of a multi-agent workflow.\n\n"
        f"### Original Task\n{run.get('initial_prompt', 'N/A')}\n\n"
        f"### Workflow Output ({len(steps)} {step_label}, {duration:.1f}s)\n"
        f"{(last_output or 'No output available.')[:5000]}\n\n"
        f"---\n"
        f"The user may ask follow-up questions, request modifications, or want to build on this output."
    )
