"""Shared instructions for agent-authored files, in addition to route exporters.

Appended to the orchestrator prompt and to every specialist's prompt. Since the
2026-09-26 sandbox (review P0-2) the agent has no shell / Python / file-writing
tool: files are produced only by the ``create_document`` and ``html_dashboard``
MCP tools, which apply the zero-draft marks themselves.
"""
from synapsis.exporters.watermark import WATERMARK_BANNER

EXPORT_INSTRUCTIONS = f"""## Mandatory AI zero-draft marks on deliverables
Every downloadable output is an AI-assisted draft and must visibly carry:
**{WATERMARK_BANNER}**. Produce files ONLY with `mcp__synapsis__create_document`
(Word, Excel, CSV, Markdown) or `mcp__synapsis__html_dashboard` (interactive
dashboard): both add the notice, the PRMS snapshot line and the UTC generation
timestamp automatically, and save the file where only the requesting user can
download it. There is no other way to write a file — do not claim otherwise.
When briefing another agent, keep this requirement. Do not describe any output
as approved or human-validated, and do not add personal contacts to exports.
State the actual source snapshot separately from the export generation date.
"""
