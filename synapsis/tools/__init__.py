"""
Innovation Analytics MCP tools — the in-process ``synapsis`` MCP server.

IA-only tool set (sandbox 2026-09-26, review P0-2 / L1-04 / L3-09 / L6-07):
PRMS data (query, search, scenarios, partners), charts, dashboards, documents
(``create_document`` — the only way to produce a downloadable file) and the
caller's own chat history.

Removed from the server (modules kept for their unit tests / later deletion):
memory_* (global across users), agent_* (custom agents injected into every
user's chat), slack_notify, fleet_* (spawned a ``claude`` shell agent),
image_generate / image_edit (unmetered OpenAI calls, arbitrary server paths),
tts_set_voice / tts_get_voices (process-global voice settings), and the
macOS-only computer-use server.
"""

from claude_agent_sdk import create_sdk_mcp_server

from synapsis.tools.history import history_search, history_retrieve, history_index, history_list
from synapsis.tools.prms_query import prms_query
from synapsis.tools.prms_search import prms_search
from synapsis.tools.create_chart import create_chart
from synapsis.tools.scenario_analysis import scenario_analysis
from synapsis.tools.partner_identification import partner_identification
from synapsis.tools.html_dashboard import html_dashboard
from synapsis.tools.create_document import create_document

#: The tools exposed to the agent. agent_options.IA_MCP_TOOLS must match
#: (tests/test_agent_sandbox.py pins both).
IA_TOOLS = [
    history_search,
    history_retrieve,
    history_index,
    history_list,
    prms_query,
    prms_search,
    create_chart,
    scenario_analysis,
    partner_identification,
    html_dashboard,
    create_document,
]

synapsis_mcp = create_sdk_mcp_server(
    name="synapsis",
    version="1.0.0",
    tools=IA_TOOLS,
)
