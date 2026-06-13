"""
HTML dashboard MCP tool — generates a self-contained interactive dashboard.

The agent calls this tool with a title and a list of sections (KPI cards,
charts, tables, text). The tool renders a single standalone ``.html`` file
(Chart.js loaded from CDN) to ``~/workspace/outputs/exports/`` and returns the
absolute file path. The frontend renders workspace file paths as downloadable
links automatically, so the user can open the dashboard in any browser.

Section shapes (see synapsis/exporters/html_dashboard.py for full detail):

- KPI cards:
    {"type": "kpi", "title": "...", "cards": [{"label": "...", "value": "..."}]}
- Chart (bar/line/pie/doughnut/scatter/area):
    {"type": "chart", "title": "...", "chart_type": "bar",
     "labels": ["A", "B"], "datasets": [{"label": "Count", "data": [1, 2]}]}
- Table (sortable + filterable):
    {"type": "table", "title": "...", "columns": ["X", "Y"],
     "rows": [["a", 1], ["b", 2]]}
- Text / narrative:
    {"type": "text", "title": "...", "content": "..."}
"""

import json
from typing import Any

from claude_agent_sdk import tool

from synapsis.config import logger, WORKSPACE
from synapsis.exporters.html_dashboard import generate_html_dashboard
from synapsis.utils.responses import error_response, success_response


def _coerce_sections(raw: Any) -> list[dict] | None:
    """Accept a list of dicts or a JSON-encoded string; return list[dict]."""
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list):
        return None
    return [s for s in raw if isinstance(s, dict)]


@tool(
    "html_dashboard",
    "Generate a self-contained, interactive HTML dashboard file the user can "
    "download and open in any browser. Use this when the user asks for a "
    "'dashboard', an 'interactive report', or a downloadable visual summary of "
    "data (e.g. innovation use by geography, portfolio overview). The dashboard "
    "supports KPI cards, interactive Chart.js charts (bar/line/pie/doughnut/"
    "scatter/area), sortable+filterable data tables, and narrative text — all "
    "embedded in ONE .html file (Chart.js via CDN). Pass a title and a JSON "
    "array of section objects. Each section needs a 'type' of 'kpi', 'chart', "
    "'table', or 'text'. The tool saves the file to "
    "~/workspace/outputs/exports/ and returns the absolute path; include that "
    "path in your reply so the user gets a download link.",
    {
        "title": str,
        "sections": list,
    },
)
async def html_dashboard(args: dict[str, Any]) -> dict[str, Any]:
    """Render a standalone interactive HTML dashboard and return its path."""
    title = (args.get("title") or "").strip()
    if not title:
        return error_response(
            "Missing required parameter 'title'. Provide a dashboard title."
        )

    sections = _coerce_sections(args.get("sections"))
    if not sections:
        return error_response(
            "Missing or invalid 'sections'. Provide a JSON array of section "
            "objects, each with a 'type' of 'kpi', 'chart', 'table', or 'text'. "
            "Example: [{\"type\": \"kpi\", \"cards\": [{\"label\": \"Total\", "
            "\"value\": \"5,615\"}]}, {\"type\": \"chart\", \"chart_type\": "
            "\"bar\", \"title\": \"By type\", \"labels\": [\"Tech\", \"Policy\"], "
            "\"datasets\": [{\"label\": \"Count\", \"data\": [120, 40]}]}]"
        )

    valid_types = {"kpi", "chart", "table", "text"}
    bad = [s.get("type") for s in sections if s.get("type") not in valid_types]
    if bad:
        return error_response(
            f"Unsupported section type(s): {bad}. "
            f"Each section 'type' must be one of: {', '.join(sorted(valid_types))}."
        )

    try:
        output_dir = WORKSPACE / "outputs" / "exports"
        path = generate_html_dashboard(title, sections, output_dir=output_dir)
    except Exception as exc:  # noqa: BLE001 — surface any render failure to the agent
        logger.error("html_dashboard generation failed: %s", exc)
        return error_response(f"Dashboard generation failed: {exc}")

    n_charts = sum(1 for s in sections if s.get("type") == "chart")
    n_tables = sum(1 for s in sections if s.get("type") == "table")
    n_kpi = sum(1 for s in sections if s.get("type") == "kpi")

    logger.info("html_dashboard saved: %s (%d sections)", path, len(sections))

    msg = (
        f"Interactive HTML dashboard generated successfully.\n\n"
        f"**File:** `{path}`\n"
        f"**Title:** {title}\n"
        f"**Sections:** {len(sections)} "
        f"({n_kpi} KPI, {n_charts} chart, {n_tables} table)\n\n"
        f"The file is self-contained (Chart.js via CDN) and can be opened in any "
        f"browser. Share the file path above so the user can download it."
    )
    return success_response(msg)
