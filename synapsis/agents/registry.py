"""
Agent registry -- auto-generated from SUBAGENTS + display metadata.

Provides the AGENT_REGISTRY dict used by the frontend API to list agents
with their display names, colors, tags, and model info.  Also exports
get_agent_display_name() for deriving human-readable names from agent IDs.
"""

import re

from claude_agent_sdk import AgentDefinition

from synapsis.constants import DEFAULT_AGENT_COLOR, ORCHESTRATOR_COLOR
from synapsis.agents.definitions import SUBAGENTS


# ---------------------------------------------------------------------------
# Agent display name utility (shared -- used by workflow executor, step runner,
# routes, etc.)
# ---------------------------------------------------------------------------

def get_agent_display_name(agent_id: str, agent_def=None) -> str:
    """Derive a human-readable display name for an agent.

    First converts the agent_id to title case (e.g. "data_analysis" ->
    "Data Analysis"). If an AgentDefinition is provided, attempts to
    extract a richer name from the first markdown bold in its prompt
    (e.g. "**Data Analysis Specialist**" -> "Data Analysis Specialist").

    Args:
        agent_id:  The snake_case agent identifier string.
        agent_def: Optional AgentDefinition whose prompt may contain a
                   bold name on the first line.

    Returns:
        The display name string.
    """
    agent_name = agent_id.replace("_", " ").title()
    if agent_def:
        first_line = agent_def.prompt.strip().split("\n")[0]
        if "**" in first_line:
            match = re.search(r"\*\*(.+?)\*\*", first_line)
            if match:
                agent_name = match.group(1)
    return agent_name


# ---------------------------------------------------------------------------
# Display metadata for builtin agents (color, tags, type)
# ---------------------------------------------------------------------------

_AGENT_DISPLAY_META: dict[str, dict] = {
    "data_analysis": {
        "type": "Statistical Analysis",
        "color": "hsl(220, 70%, 50%)",
        "tags": ["EDA", "Regression", "Hypothesis Testing", "Time Series"],
    },
    "visualization_reporting": {
        "type": "Data Visualization",
        "color": "hsl(175, 70%, 50%)",
        "tags": ["Charts", "Dashboards", "Reports", "matplotlib", "plotly"],
    },
    "research_methodology": {
        "type": "Study Design",
        "color": "hsl(142, 70%, 50%)",
        "tags": ["Power Analysis", "Sampling", "RCT", "Quasi-Experimental"],
    },
    "code_automation": {
        "type": "Data Engineering",
        "color": "hsl(280, 70%, 50%)",
        "tags": ["ETL", "Pipelines", "Web Scraping", "API Integration"],
    },
    "computer_use": {
        "type": "Computer Use",
        "color": "hsl(200, 70%, 50%)",
        "tags": ["Browser", "Documents", "GUI", "Screenshots"],
    },

    # -- CGIAR domain specialists --
    "prms_data_analyst": {
        "type": "PRMS Database",
        "color": "hsl(30, 70%, 50%)",
        "tags": ["PRMS", "SQL", "Data Analysis", "Source Attribution"],
    },
    "innovation_strategy_advisor": {
        "type": "Innovation Strategy",
        "color": "hsl(340, 70%, 50%)",
        "tags": ["IRL", "Scaling", "Portfolio", "Strategy"],
    },
    "research_synthesizer": {
        "type": "Research Synthesis",
        "color": "hsl(50, 70%, 50%)",
        "tags": ["Briefings", "Synthesis", "Evidence", "Landscape"],
    },
    "report_generator": {
        "type": "Report Generation",
        "color": "hsl(100, 70%, 50%)",
        "tags": ["Reports", "Executive Summary", "Tables", "Formatting"],
    },
}


def _build_registry(
    subagents: dict[str, AgentDefinition],
    display_meta: dict[str, dict],
) -> dict[str, dict]:
    """Auto-generate the full agent registry from SUBAGENTS and display metadata.

    For each base agent, derives the display name via get_agent_display_name()
    and merges in the extra display metadata (color, tags, type). Opus and
    Sonnet variant entries are generated automatically with adjusted color
    saturation/lightness and an appended model tag.

    The orchestrator entry is added manually since it is not an AgentDefinition.
    """
    registry: dict[str, dict] = {
        "orchestrator": {
            "name": "Orchestrator (Full Team)",
            "description": (
                "The main orchestrator with access to all subagents. When used as a "
                "workflow step, it can delegate to any specialist agent -- making the "
                "step a full agentic team."
            ),
            "type": "builtin",
            "tools": ["All tools + Task delegation"],
            "model": "opus",
            "color": ORCHESTRATOR_COLOR,
            "tags": ["Orchestrator", "Team", "Multi-Agent"],
        },
    }

    # Helper to adjust HSL color for variants
    def _adjust_hsl(color: str, saturation: int, lightness: int) -> str:
        """Replace saturation and lightness in an HSL string."""
        hsl_match = re.match(r"hsl\((\d+),\s*\d+%,\s*\d+%\)", color)
        if hsl_match:
            hue = hsl_match.group(1)
            return f"hsl({hue}, {saturation}%, {lightness}%)"
        return color

    for agent_id, agent_def in subagents.items():
        # Skip variant entries -- they are generated below
        if agent_id.endswith("_opus_powerful") or agent_id.endswith("_sonnet_efficient"):
            continue

        meta = display_meta.get(agent_id, {})
        base_name = get_agent_display_name(agent_id, agent_def)
        base_color = meta.get("color", DEFAULT_AGENT_COLOR)
        base_tags = meta.get("tags", [])
        base_type = meta.get("type", "builtin")

        # Base entry
        registry[agent_id] = {
            "name": base_name,
            "type": base_type,
            "color": base_color,
            "tags": list(base_tags),
        }

        # Opus (Powerful) variant
        opus_key = f"{agent_id}_opus_powerful"
        if opus_key in subagents:
            registry[opus_key] = {
                "name": f"{base_name} (Opus/Powerful)",
                "type": base_type,
                "color": _adjust_hsl(base_color, 85, 40),
                "tags": list(base_tags) + ["Opus"],
            }

        # Sonnet (Efficient) variant
        sonnet_key = f"{agent_id}_sonnet_efficient"
        if sonnet_key in subagents:
            registry[sonnet_key] = {
                "name": f"{base_name} (Sonnet/Efficient)",
                "type": base_type,
                "color": _adjust_hsl(base_color, 50, 60),
                "tags": list(base_tags) + ["Sonnet"],
            }

    return registry


AGENT_REGISTRY: dict[str, dict] = _build_registry(SUBAGENTS, _AGENT_DISPLAY_META)
