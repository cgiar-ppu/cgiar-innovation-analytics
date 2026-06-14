"""
Chart generation MCP tool -- creates interactive chart specifications.

The agent calls this tool with chart parameters (type, title, data, series),
and the tool validates the inputs, applies CGIAR brand colors, and returns
a structured JSON chart specification wrapped in <chart> tags.

The frontend's chartDetector.ts automatically detects <chart> tags in assistant
messages and renders them as interactive Recharts visualizations inline.

Flow:
1. Agent queries PRMS for data → gets tabular results
2. Agent calls create_chart with the data + desired chart config
3. Tool validates, enriches (colors, series inference), and returns <chart> spec
4. Agent includes the <chart> block in its response text
5. Frontend auto-renders the chart
"""

import json
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response


# ---------------------------------------------------------------------------
# CGIAR brand palette for chart series
# ---------------------------------------------------------------------------

CGIAR_CHART_COLORS: list[str] = [
    "#427730",   # CGIAR Forest Green (primary)
    "#7AB800",   # CGIAR Lime Green
    "#0065BD",   # CGIAR Blue
    "#E37222",   # CGIAR Orange
    "#8B1A4A",   # CGIAR Burgundy
    "#00A5DB",   # CGIAR Sky Blue
    "#F4B223",   # CGIAR Gold
    "#5C3D8F",   # CGIAR Purple
    "#009E73",   # CGIAR Teal
    "#D32F2F",   # CGIAR Red
]
"""Ten-color palette based on CGIAR brand guidelines, chosen for distinguishability."""


VALID_CHART_TYPES: list[str] = [
    "bar", "line", "area", "pie", "scatter", "multiBar", "stackedArea",
]
"""Chart types supported by the frontend InteractiveChart component."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_data(data: Any) -> str | None:
    """Validate the data parameter. Returns error message or None if valid."""
    if not isinstance(data, list):
        return "The 'data' parameter must be a JSON array of objects."
    if len(data) < 2:
        return "Chart data must contain at least 2 data points."
    if len(data) > 200:
        return (
            f"Chart data has {len(data)} items — this is too many for a readable chart. "
            "Please limit to 50 items or fewer. Consider aggregating or filtering the data."
        )
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return f"Data item at index {i} is not an object. All items must be JSON objects."
    return None


def _validate_series(series: Any) -> str | None:
    """Validate the series parameter if provided. Returns error or None."""
    if series is None:
        return None
    if not isinstance(series, list):
        return "The 'series' parameter must be an array of objects."
    for i, s in enumerate(series):
        if not isinstance(s, dict):
            return f"Series item at index {i} is not an object."
        if "key" not in s:
            return f"Series item at index {i} is missing required 'key' field."
    return None


def _looks_numeric(value: Any) -> bool:
    """Check if a value is numeric or a string that can be parsed as a number."""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        try:
            float(cleaned)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _infer_series(data: list[dict], x_axis_key: str | None) -> list[dict]:
    """Auto-infer series configuration from data keys.

    Finds all numeric-valued keys in the first data item (excluding x_axis_key)
    and creates a series entry for each. Also detects string values that look
    numeric (e.g., "1,234" or "56%").
    """
    if not data:
        return []
    sample = data[0]
    series = []
    for key, value in sample.items():
        if key == x_axis_key:
            continue
        if _looks_numeric(value):
            # Convert key to title case for the label
            label = key.replace("_", " ").title()
            series.append({"key": key, "label": label})
    return series


def _apply_colors(series: list[dict]) -> list[dict]:
    """Apply CGIAR brand colors to series that don't have explicit colors."""
    result = []
    for i, s in enumerate(series):
        entry = dict(s)
        if "color" not in entry:
            entry["color"] = CGIAR_CHART_COLORS[i % len(CGIAR_CHART_COLORS)]
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------

@tool(
    "create_chart",
    "Generate an interactive chart specification for inline rendering. "
    "Pass chart type, title, data array, and optional series/axis config. "
    "The returned <chart> block renders as an interactive Recharts visualization "
    "in the user's chat. Supported types: bar, line, area, pie, scatter, "
    "multiBar, stackedArea. Data should be an array of objects with consistent keys.",
    {
        "chart_type": str,
        "title": str,
        "data": list,
        "x_axis_key": str,
        "series": list,
        "description": str,
    },
)
async def create_chart(args: dict[str, Any]) -> dict[str, Any]:
    """Generate a chart specification for the frontend to render.

    Args (via tool schema):
        chart_type (required): One of 'bar', 'line', 'area', 'pie', 'scatter',
                               'multiBar', 'stackedArea'.
        title (required): Chart title displayed above the visualization.
        data (required): Array of objects -- each object is a data point.
                         Example: [{"region": "East Africa", "count": 150}, ...]
        x_axis_key (optional): Key in data objects for the x-axis / category.
                               If omitted, auto-detected as the first string-valued key.
        series (optional): Array of series configs. Each has 'key' (required),
                          'label' (optional), 'color' (optional hex).
                          If omitted, inferred from numeric keys in data.
        description (optional): Brief description shown below the chart title.

    Returns:
        MCP response with the chart specification in <chart> tags, ready for
        the agent to include in its response text.
    """
    chart_type = args.get("chart_type", "").strip()
    title = args.get("title", "").strip()
    data = args.get("data")
    x_axis_key = args.get("x_axis_key", "").strip() or None
    series = args.get("series")
    description = args.get("description", "").strip() or None

    # --- Validation ---

    if not chart_type:
        return error_response(
            "Missing required parameter 'chart_type'. "
            f"Must be one of: {', '.join(VALID_CHART_TYPES)}"
        )

    if chart_type not in VALID_CHART_TYPES:
        return error_response(
            f"Invalid chart_type '{chart_type}'. "
            f"Must be one of: {', '.join(VALID_CHART_TYPES)}"
        )

    if not title:
        return error_response("Missing required parameter 'title'. Provide a descriptive chart title.")

    if data is None:
        return error_response(
            "Missing required parameter 'data'. "
            "Provide an array of objects, e.g. [{\"region\": \"East Africa\", \"count\": 150}, ...]"
        )

    data_error = _validate_data(data)
    if data_error:
        return error_response(data_error)

    series_error = _validate_series(series)
    if series_error:
        return error_response(series_error)

    # --- Auto-detect x_axis_key if not provided ---

    if not x_axis_key and data:
        sample = data[0]
        for key, value in sample.items():
            if isinstance(value, str):
                x_axis_key = key
                break

    # --- Infer series if not provided ---

    if not series:
        series = _infer_series(data, x_axis_key)
        if not series:
            return error_response(
                "Could not infer chart series — no numeric keys found in data. "
                "Please provide explicit 'series' parameter with at least one "
                "entry like [{\"key\": \"count\", \"label\": \"Count\"}]."
            )

    # --- Apply CGIAR brand colors ---

    series = _apply_colors(series)

    # --- Ensure data values are numbers for numeric series ---

    series_keys = {s["key"] for s in series}
    cleaned_data = []
    for item in data:
        row = dict(item)
        for key in series_keys:
            if key in row:
                val = row[key]
                if isinstance(val, str):
                    try:
                        row[key] = float(val.replace(",", ""))
                    except (ValueError, TypeError):
                        row[key] = 0
        cleaned_data.append(row)

    # --- Build the chart specification ---

    chart_spec: dict[str, Any] = {
        "chartType": chart_type,
        "title": title,
        "data": cleaned_data,
        "series": series,
    }

    if x_axis_key:
        chart_spec["xAxisKey"] = x_axis_key

    if description:
        chart_spec["description"] = description

    # --- Format the response ---

    chart_json = json.dumps(chart_spec, indent=2, ensure_ascii=False)

    response_text = (
        f"Chart generated successfully: **{title}** ({chart_type} chart, "
        f"{len(cleaned_data)} data points, {len(series)} series).\n\n"
        f"Include the following block in your response to render the chart:\n\n"
        f"<chart>\n{chart_json}\n</chart>"
    )

    return success_response(response_text)
