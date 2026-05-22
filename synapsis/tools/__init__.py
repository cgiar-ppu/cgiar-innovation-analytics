"""
Synapsis MCP tools — memory persistence, agent management, and Slack notifications.
Computer use tools live in a separate 'computer-use' MCP server.
"""

from claude_agent_sdk import create_sdk_mcp_server

from synapsis.tools.memory import memory_store, memory_recall, memory_list, memory_forget
from synapsis.tools.agents import agent_create, agent_list, agent_update
from synapsis.tools.slack import slack_notify
from synapsis.tools.fleet import fleet_create, fleet_spawn, fleet_resume, fleet_mediate, fleet_status, fleet_inspect, fleet_initialize
from synapsis.tools.tts import tts_set_voice, tts_get_voices
from synapsis.tools.history import history_search, history_retrieve, history_index, history_list
from synapsis.tools.prms_query import prms_query
from synapsis.tools.create_chart import create_chart

# ---------------------------------------------------------------------------
# Memory + agent management + Slack MCP server
# ---------------------------------------------------------------------------

synapsis_mcp = create_sdk_mcp_server(
    name="synapsis",
    version="1.0.0",
    tools=[
        memory_store,
        memory_recall,
        memory_list,
        memory_forget,
        agent_create,
        agent_list,
        agent_update,
        slack_notify,
        fleet_create,
        fleet_spawn,
        fleet_resume,
        fleet_mediate,
        fleet_status,
        fleet_inspect,
        fleet_initialize,
        tts_set_voice,
        tts_get_voices,
        history_search,
        history_retrieve,
        history_index,
        history_list,
        prms_query,
        create_chart,
    ],
)

# ---------------------------------------------------------------------------
# Computer use MCP server (separate — API backend detects mcp__computer-use__* names)
# ---------------------------------------------------------------------------

from synapsis.tools.computer_use_server import computer_use_tools

computer_use_mcp = create_sdk_mcp_server(
    name="computer-use",
    version="1.0.0",
    tools=computer_use_tools,
)
