"""
Agents package -- backward-compatible re-exports.

All public names that were previously importable from ``synapsis.agents``
(when it was a single module) are re-exported here so that existing
``from synapsis.agents import X`` statements continue to work unchanged.
"""

from synapsis.agents.definitions import SUBAGENTS, _STANDARD_TOOLS  # noqa: F401
from synapsis.agents.registry import (  # noqa: F401
    AGENT_REGISTRY,
    _AGENT_DISPLAY_META,
    get_agent_display_name,
)
from synapsis.agents.loader import load_all_agents  # noqa: F401

# Re-export build_system_prompt so callers that import from agents continue
# to work without any changes (e.g. agent_options.py).
from synapsis.system_prompt import build_system_prompt  # noqa: F401
