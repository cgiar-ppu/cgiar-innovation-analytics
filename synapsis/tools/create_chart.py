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
import re
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


#: Written-out "no value" markers. They become ``None`` (a gap in the chart),
#: never 0 — review L6-04: "n/a" used to be plotted as a real zero.
_MISSING_MARKERS = frozenset({
    "", "n/a", "na", "n.a.", "none", "null", "nan", "-", "--", "—", "–",
    "not available", "not reported", "not yet reported", "unknown", "?",
})

#: Currency symbols / codes and other decorations stripped before parsing.
_NUMBER_NOISE = re.compile(r"(?i)(us\$|usd|eur|gbp|kes|inr|[$€£¥₹%\s\u00a0\u202f,'_])")


def parse_number(value: Any) -> tuple[float | int | None, bool]:
    """The ONE numeric parser for chart values. Returns ``(number, ok)``.

    * ints/floats pass through (``bool`` is not a number);
    * strings: ``%``, thousands separators (``,`` and spaces), currency
      symbols/codes and a trailing ``%`` are stripped — ``"56%"`` → 56,
      ``"1,234"`` → 1234, ``"$ 2.5"`` → 2.5, ``"(12)"`` → -12;
    * missing markers (``""``, ``"n/a"``, ``"—"``, ``None`` …) → ``(None, True)``:
      a deliberate gap;
    * anything else unparseable (``"1.2k"``, ``"about 40"``) → ``(None, False)``:
      also a gap, and the caller warns the agent.
    """
    if value is None:
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:  # NaN
            return None, True
        return value, True
    if not isinstance(value, str):
        return None, False
    raw = value.strip()
    if raw.lower() in _MISSING_MARKERS:
        return None, True
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    cleaned = _NUMBER_NOISE.sub("", raw).replace("\u2212", "-")
    if not cleaned:
        return None, False
    try:
        number = float(cleaned)
    except ValueError:
        return None, False
    if number != number or number in (float("inf"), float("-inf")):
        return None, False
    if negative:
        number = -number
    return (int(number) if number.is_integer() and "." not in cleaned and "e" not in cleaned.lower() else number), True


def _looks_numeric(value: Any) -> bool:
    """Whether a value is a number (or a string :func:`parse_number` can read)."""
    number, ok = parse_number(value)
    return ok and number is not None


def _infer_series(data: list[dict], x_axis_key: str | None) -> list[dict]:
    """Auto-infer series configuration from data keys.

    A key becomes a series when at least one row carries a number for it
    (numbers, or strings :func:`parse_number` can read such as "1,234" or
    "56%"); looking at every row means a first row with "n/a" does not hide
    the series.
    """
    if not data:
        return []
    keys: list[str] = []
    for item in data:
        for key in item:
            if key not in keys:
                keys.append(key)
    series = []
    for key in keys:
        if key == x_axis_key:
            continue
        if any(_looks_numeric(item.get(key)) for item in data):
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
        # Prefer a text column that is not a number in disguise ("56%").
        text_keys = [k for k, v in sample.items() if isinstance(v, str)]
        x_axis_key = next((k for k in text_keys if not _looks_numeric(sample[k])), None)
        if x_axis_key is None and text_keys:
            x_axis_key = text_keys[0]

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
    # One parser for every value (review L6-04): "56%" → 56, "1,234" → 1234,
    # "n/a" / blank → None (a gap in the chart, never a fake 0). Values that
    # could not be read are reported back to the agent.

    series_keys = [s["key"] for s in series]
    cleaned_data = []
    unreadable: list[str] = []
    gaps = 0
    for item in data:
        row = dict(item)
        for key in series_keys:
            if key not in row:
                continue
            number, ok = parse_number(row[key])
            if number is None:
                gaps += 1
                if not ok:
                    unreadable.append(f"{key}={row[key]!r}")
            row[key] = number
        cleaned_data.append(row)

    plotted = sum(1 for r in cleaned_data for k in series_keys if isinstance(r.get(k), (int, float)))
    if plotted == 0:
        return error_response(
            "None of the series values could be read as numbers "
            f"(e.g. {', '.join(unreadable[:3]) or 'all values are missing'}). "
            "Pass plain numbers such as 1185 or 56.2 (percentages without the % sign are fine)."
        )

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

    warning = ""
    if gaps:
        warning = (
            f"\n\nNote: {gaps} value(s) are missing and are shown as gaps, not zeros"
            + (f"; these could not be read as numbers: {', '.join(unreadable[:10])}"
               + (" …" if len(unreadable) > 10 else "") if unreadable else "")
            + ". Say so in your answer, or pass plain numbers and call create_chart again."
        )

    response_text = (
        f"Chart generated successfully: **{title}** ({chart_type} chart, "
        f"{len(cleaned_data)} data points, {len(series)} series).{warning}\n\n"
        f"Include the following block in your response to render the chart:\n\n"
        f"<chart>\n{chart_json}\n</chart>"
    )

    return success_response(response_text)
