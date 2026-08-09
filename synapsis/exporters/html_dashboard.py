"""
Standalone interactive HTML dashboard generator.

Produces a single self-contained ``.html`` file that the user can download and
open in any browser. Charts are rendered with Chart.js loaded from a CDN, so
the file has no local dependencies beyond an internet connection for the CDN.

A dashboard is described as a *title* plus an ordered list of *sections*. Each
section is a dict with a ``type`` key:

- ``"kpi"``   — a row of KPI / summary stat cards.
    {"type": "kpi", "title": "Portfolio at a glance",
     "cards": [{"label": "Total innovations", "value": "5,615"}, ...]}

- ``"chart"`` — a Chart.js chart (bar, line, pie, doughnut, scatter).
    {"type": "chart", "title": "Innovations by type", "chart_type": "bar",
     "labels": ["Tech", "Capacity", "Policy"], "datasets": [
         {"label": "Count", "data": [120, 80, 40]}]}

- ``"table"`` — a sortable / filterable data table.
    {"type": "table", "title": "Top initiatives",
     "columns": ["Initiative", "Count"],
     "rows": [["INIT-01", 42], ["INIT-02", 31]]}

- ``"text"``  — a free-text / markdown-ish narrative block (HTML-escaped).
    {"type": "text", "title": "Notes", "content": "..."}

The module is intentionally template-driven and dependency-free on the Python
side (only the stdlib). All rendering helpers live here; the agent-facing MCP
tool in ``synapsis/tools/html_dashboard.py`` calls ``generate_html_dashboard``.
"""

from __future__ import annotations

import html as html_module
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .watermark import watermark_html, watermark_html_overlay, WATERMARK_HTML_CSS

# CGIAR brand palette (mirrors synapsis/tools/create_chart.py)
CGIAR_COLORS: list[str] = [
    "#427730", "#7AB800", "#0065BD", "#E37222", "#8B1A4A",
    "#00A5DB", "#F4B223", "#5C3D8F", "#009E73", "#D32F2F",
]

CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

VALID_CHART_TYPES = {"bar", "line", "pie", "doughnut", "scatter", "area"}


# ---------------------------------------------------------------------------
# Section renderers — each returns an HTML string
# ---------------------------------------------------------------------------

def _esc(value: Any) -> str:
    """HTML-escape an arbitrary value rendered as text."""
    return html_module.escape("" if value is None else str(value))


def _render_kpi(section: dict, idx: int) -> str:
    cards = section.get("cards", []) or []
    title = section.get("title", "")
    card_html = []
    for c in cards:
        label = _esc(c.get("label", ""))
        value = _esc(c.get("value", ""))
        sub = _esc(c.get("sub", "")) if c.get("sub") else ""
        sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
        card_html.append(
            f'<div class="kpi-card"><div class="kpi-value">{value}</div>'
            f'<div class="kpi-label">{label}</div>{sub_html}</div>'
        )
    title_html = f'<h2>{_esc(title)}</h2>' if title else ""
    return f'<section>{title_html}<div class="kpi-row">{"".join(card_html)}</div></section>'


def _render_chart(section: dict, idx: int) -> str:
    chart_type = section.get("chart_type", "bar")
    if chart_type == "area":
        chart_type = "line"  # area is line + fill, handled in JS config
    if chart_type not in VALID_CHART_TYPES:
        chart_type = "bar"
    title = _esc(section.get("title", "Chart"))
    canvas_id = f"chart_{idx}"
    return (
        f'<section><h2>{title}</h2>'
        f'<div class="chart-wrap"><canvas id="{canvas_id}"></canvas></div></section>'
    )


def _render_table(section: dict, idx: int) -> str:
    title = _esc(section.get("title", "Table"))
    columns = section.get("columns", []) or []
    rows = section.get("rows", []) or []
    table_id = f"table_{idx}"

    head = "".join(f"<th>{_esc(col)}</th>" for col in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows)

    return (
        f'<section><h2>{title}</h2>'
        f'<input class="table-filter" type="text" placeholder="Filter rows…" '
        f'data-table="{table_id}" oninput="filterTable(this)">'
        f'<table id="{table_id}" class="data-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>"
    )


def _render_text(section: dict, idx: int) -> str:
    title = section.get("title", "")
    content = _esc(section.get("content", "")).replace("\n", "<br>")
    title_html = f"<h2>{_esc(title)}</h2>" if title else ""
    return f'<section>{title_html}<div class="text-block">{content}</div></section>'


_RENDERERS = {
    "kpi": _render_kpi,
    "chart": _render_chart,
    "table": _render_table,
    "text": _render_text,
}


# ---------------------------------------------------------------------------
# Chart.js config builder (emitted as JS)
# ---------------------------------------------------------------------------

def _build_chart_js(sections: list[dict]) -> str:
    """Emit the JavaScript that instantiates every Chart.js chart."""
    blocks: list[str] = []
    for idx, section in enumerate(sections):
        if section.get("type") != "chart":
            continue
        raw_type = section.get("chart_type", "bar")
        is_area = raw_type == "area"
        chart_type = "line" if is_area else (raw_type if raw_type in VALID_CHART_TYPES else "bar")

        labels = section.get("labels", []) or []
        datasets = section.get("datasets", []) or []

        # Color each dataset; pie/doughnut color per-point instead of per-series
        enriched = []
        for d_i, ds in enumerate(datasets):
            ds = dict(ds)
            if chart_type in ("pie", "doughnut"):
                ds["backgroundColor"] = CGIAR_COLORS[: max(1, len(labels))]
            else:
                color = CGIAR_COLORS[d_i % len(CGIAR_COLORS)]
                ds.setdefault("backgroundColor", color)
                ds.setdefault("borderColor", color)
                if is_area:
                    ds.setdefault("fill", True)
                ds.setdefault("borderWidth", 2)
            enriched.append(ds)

        config = {
            "type": chart_type,
            "data": {"labels": labels, "datasets": enriched},
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {"legend": {"display": True}},
            },
        }
        blocks.append(
            f"new Chart(document.getElementById('chart_{idx}'), "
            f"{json.dumps(config, ensure_ascii=False)});"
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Inline CSS + JS
# ---------------------------------------------------------------------------

_STYLES = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; background: #f4f6f4; color: #1a1a2e; line-height: 1.5; }
  header { background: #427730; color: #fff; padding: 1.5rem 2rem; }
  header h1 { margin: 0; font-size: 1.6rem; }
  header .meta { opacity: 0.85; font-size: 0.85rem; margin-top: 0.25rem; }
  main { max-width: 1100px; margin: 0 auto; padding: 1.5rem 2rem 3rem; }
  section { background: #fff; border-radius: 12px; padding: 1.25rem 1.5rem;
            margin: 1.25rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  section h2 { margin-top: 0; color: #427730; font-size: 1.15rem; }
  .kpi-row { display: flex; flex-wrap: wrap; gap: 1rem; }
  .kpi-card { flex: 1 1 160px; background: #f0f6ee; border-left: 4px solid #427730;
              border-radius: 8px; padding: 1rem; }
  .kpi-value { font-size: 1.8rem; font-weight: 700; color: #2e5a20; }
  .kpi-label { font-size: 0.85rem; color: #555; }
  .kpi-sub { font-size: 0.75rem; color: #888; margin-top: 0.25rem; }
  .chart-wrap { position: relative; height: 360px; }
  .data-table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  .data-table th, .data-table td { border: 1px solid #e0e0e0; padding: 0.5rem 0.7rem; text-align: left; }
  .data-table th { background: #f0f6ee; cursor: pointer; user-select: none; }
  .data-table tbody tr:nth-child(even) { background: #fafbfa; }
  .table-filter { margin-bottom: 0.6rem; padding: 0.4rem 0.6rem; width: 100%;
                  max-width: 320px; border: 1px solid #ccc; border-radius: 6px; }
  .text-block { color: #333; }
  footer { text-align: center; color: #888; font-size: 0.8rem; padding: 1.5rem; }
"""

_TABLE_JS = """
function filterTable(input) {
  const q = input.value.toLowerCase();
  const table = document.getElementById(input.dataset.table);
  table.querySelectorAll('tbody tr').forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
document.querySelectorAll('table.data-table thead th').forEach((th, col) => {
  th.addEventListener('click', () => {
    const tbody = th.closest('table').querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const asc = !(th.dataset.asc === 'true');
    th.dataset.asc = asc;
    rows.sort((a, b) => {
      const av = a.children[col].textContent.trim();
      const bv = b.children[col].textContent.trim();
      const an = parseFloat(av.replace(/,/g, '')), bn = parseFloat(bv.replace(/,/g, ''));
      const cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
      return asc ? cmp : -cmp;
    });
    rows.forEach(r => tbody.appendChild(r));
  });
});
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_dashboard_html(title: str, sections: list[dict]) -> str:
    """Render a complete standalone HTML document string for the dashboard."""
    safe_title = _esc(title)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    body_parts: list[str] = []
    for idx, section in enumerate(sections):
        renderer = _RENDERERS.get(section.get("type", ""))
        if renderer is None:
            continue
        body_parts.append(renderer(section, idx))

    chart_js = _build_chart_js(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<script src="{CHARTJS_CDN}"></script>
<style>{_STYLES}
{WATERMARK_HTML_CSS}</style>
</head>
<body>
{watermark_html_overlay()}
<header>
  <h1>{safe_title}</h1>
  <div class="meta">CGIAR Innovation Analytics · Generated {generated_at}</div>
</header>
<main>
{watermark_html()}
{chr(10).join(body_parts)}
</main>
<footer>Self-contained dashboard generated by the CGIAR Innovation Analytics Platform.</footer>
<script>
{_TABLE_JS}
window.addEventListener('DOMContentLoaded', function () {{
{chart_js}
}});
</script>
</body>
</html>"""


def generate_html_dashboard(
    title: str,
    sections: list[dict],
    output_dir: Path | str | None = None,
) -> str:
    """Generate a dashboard HTML file and return its absolute path.

    Args:
        title:      Dashboard title shown in the header and browser tab.
        sections:   Ordered list of section dicts (see module docstring).
        output_dir: Directory to write into. Defaults to
                    ``WORKSPACE/outputs/exports`` (i.e. ``/workspace/outputs/exports``
                    in the container, matching the /api/files/ serve path).

    Returns:
        The absolute path (str) to the written ``.html`` file.
    """
    if output_dir is None:
        # Derive from WORKSPACE (env-configurable) so the default matches the
        # path the /api/files/ route serves from. Using Path.home() here breaks
        # downloads in the container, where home (/home/synapsis) != WORKSPACE
        # (/workspace) and the file-serving route only looks under WORKSPACE.
        from synapsis.config import WORKSPACE

        output_dir = WORKSPACE / "outputs" / "exports"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"{timestamp}_dashboard.html"
    out_path.write_text(render_dashboard_html(title, sections), encoding="utf-8")
    return str(out_path.resolve())
