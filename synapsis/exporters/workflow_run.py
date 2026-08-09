"""Export workflow run logs to Markdown and HTML formats."""

import html as html_lib
import json
from datetime import datetime

from .common import safe_filename
from .watermark import (
    watermark_markdown,
    watermark_markdown_footer,
    watermark_html,
    watermark_html_overlay,
    WATERMARK_HTML_CSS,
)


def export_workflow_run_markdown(run_log: dict) -> tuple[str, str]:
    """Export a workflow run log to Markdown format.

    Returns (content, filename) tuple.
    """
    name = run_log.get("workflow_name", "Workflow")
    run_id = run_log.get("run_id", run_log.get("id", "unknown"))
    status = run_log.get("status", "unknown")
    duration = run_log.get("total_duration_s", 0) or 0
    cost = run_log.get("total_estimated_cost_usd", run_log.get("total_cost_usd", 0)) or 0
    prompt = run_log.get("initial_prompt", "N/A")

    lines = []
    lines.append(f"# Workflow Run: {name}")
    lines.append("")
    # AI-content watermark / disclaimer — required at the top of every export.
    lines.append(watermark_markdown())
    lines.append("")
    lines.append(f"- **Run ID**: `{run_id[:8] if run_id else 'N/A'}`")
    lines.append(f"- **Status**: {status}")
    if run_log.get("started_at"):
        started = run_log["started_at"]
        if isinstance(started, (int, float)):
            started = datetime.fromtimestamp(started).isoformat()
        lines.append(f"- **Started**: {started}")
    if duration:
        lines.append(f"- **Duration**: {duration:.1f}s")
    if cost:
        lines.append(f"- **Estimated Cost**: ${cost:.4f}")
    lines.append("")
    lines.append("## Initial Prompt")
    lines.append("")
    lines.append(prompt)
    lines.append("")
    lines.append("---")
    lines.append("")

    steps = run_log.get("steps", [])
    for i, step in enumerate(steps):
        agent_name = step.get("agent_name", step.get("agent_id", f"Step {i+1}"))
        step_duration = step.get("duration_s", 0) or 0
        lines.append(f"## Step {i+1}: {agent_name} ({step_duration:.1f}s)")
        lines.append("")

        messages = step.get("messages", [])
        for msg in messages:
            msg_type = msg.get("type", "")

            if msg_type == "text":
                content = msg.get("content", "")
                if not content and isinstance(msg.get("data"), dict):
                    content = msg["data"].get("content", "")
                if content:
                    lines.append(content)
                    lines.append("")

            elif msg_type == "thinking":
                content = msg.get("content", "")
                if not content and isinstance(msg.get("data"), dict):
                    content = msg["data"].get("content", "")
                if content:
                    lines.append("<details>")
                    lines.append("<summary>Thinking</summary>")
                    lines.append("")
                    lines.append(content)
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

            elif msg_type == "tool_use":
                data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                tool = msg.get("tool", data.get("tool", "unknown"))
                lines.append(f"**Tool: {tool}**")
                tool_input = msg.get("input", data.get("input", ""))
                if tool_input:
                    if isinstance(tool_input, dict):
                        tool_input = json.dumps(tool_input, indent=2)
                    lines.append(f"```json\n{str(tool_input)[:1000]}\n```")
                lines.append("")

            elif msg_type == "tool_result":
                data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                content = msg.get("content", data.get("content", ""))
                is_error = msg.get("is_error", data.get("is_error", False))
                prefix = "Error" if is_error else "Result"
                lines.append(f"> **{prefix}**: {str(content)[:500]}")
                lines.append("")

        # Step output summary
        output = step.get("output_text", "")
        if output and not any(m.get("type") == "text" for m in messages):
            lines.append("### Output")
            lines.append("")
            lines.append(output)
            lines.append("")

        lines.append("---")
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Steps**: {len(steps)}")
    lines.append(f"- **Total Duration**: {duration:.1f}s")
    if cost:
        lines.append(f"- **Estimated Cost**: ${cost:.4f}")
    lines.append("")
    # Per-page-footer analogue for a format with no pages: close the document
    # with the product line + banner + provenance notice.
    lines.append(watermark_markdown_footer())

    content = "\n".join(lines)
    base = safe_filename(f"workflow_run_{name}_{run_id[:8] if run_id else 'unknown'}")
    filename = base + ".md"
    return content, filename


def export_workflow_run_html(run_log: dict) -> tuple[str, str]:
    """Export a workflow run log to HTML format.

    Returns (content, filename) tuple.
    """
    name = run_log.get("workflow_name", "Workflow")
    run_id = run_log.get("run_id", run_log.get("id", "unknown"))
    status = run_log.get("status", "unknown")
    duration = run_log.get("total_duration_s", 0) or 0
    cost = run_log.get("total_estimated_cost_usd", run_log.get("total_cost_usd", 0)) or 0
    prompt = run_log.get("initial_prompt", "N/A")

    status_colors = {
        "completed": "#22c55e",
        "failed": "#ef4444",
        "cancelled": "#f59e0b",
        "running": "#3b82f6",
    }
    status_color = status_colors.get(status, "#6b7280")

    steps_html = []
    steps = run_log.get("steps", [])
    for i, step in enumerate(steps):
        agent_name = html_lib.escape(step.get("agent_name", step.get("agent_id", f"Step {i+1}")))
        step_duration = step.get("duration_s", 0) or 0

        msgs_html = []
        messages = step.get("messages", [])
        for msg in messages:
            msg_type = msg.get("type", "")

            if msg_type == "text":
                content = msg.get("content", "")
                if not content and isinstance(msg.get("data"), dict):
                    content = msg["data"].get("content", "")
                content = html_lib.escape(content)
                if content:
                    msgs_html.append(
                        f'<div class="msg text"><pre style="white-space:pre-wrap;'
                        f'font-family:inherit;">{content}</pre></div>'
                    )

            elif msg_type == "thinking":
                content = msg.get("content", "")
                if not content and isinstance(msg.get("data"), dict):
                    content = msg["data"].get("content", "")
                content = html_lib.escape(content)
                if content:
                    msgs_html.append(
                        f'<details class="msg thinking"><summary style="cursor:pointer;'
                        f'color:#8b5cf6;">Thinking</summary><pre style="white-space:pre-wrap;'
                        f'color:#6b7280;font-size:0.85em;">{content}</pre></details>'
                    )

            elif msg_type == "tool_use":
                data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                tool = html_lib.escape(msg.get("tool", data.get("tool", "unknown")))
                tool_input = msg.get("input", data.get("input", ""))
                if isinstance(tool_input, dict):
                    tool_input = json.dumps(tool_input, indent=2)
                tool_input_esc = html_lib.escape(str(tool_input)[:1000])
                msgs_html.append(
                    f'<div class="msg tool-use"><strong>Tool: {tool}</strong>'
                    f'<pre style="background:#1e293b;color:#e2e8f0;padding:8px;'
                    f'border-radius:4px;font-size:0.85em;overflow-x:auto;">'
                    f'{tool_input_esc}</pre></div>'
                )

            elif msg_type == "tool_result":
                data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                content = html_lib.escape(str(msg.get("content", data.get("content", "")))[:500])
                is_error = msg.get("is_error", data.get("is_error", False))
                color = "#ef4444" if is_error else "#22c55e"
                label = "Error" if is_error else "Result"
                msgs_html.append(
                    f'<div class="msg tool-result" style="border-left:3px solid {color};'
                    f'padding-left:12px;"><strong>{label}:</strong> '
                    f'<span style="font-size:0.9em;">{content}</span></div>'
                )

        msgs_content = "\n".join(msgs_html)

        steps_html.append(f"""
        <div class="step" style="margin-bottom:24px;border:1px solid #334155;border-radius:8px;overflow:hidden;">
            <div style="background:#1e293b;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;">
                <h3 style="margin:0;color:#f1f5f9;">Step {i+1}: {agent_name}</h3>
                <span style="color:#94a3b8;font-size:0.85em;">{step_duration:.1f}s</span>
            </div>
            <div style="padding:16px;display:flex;flex-direction:column;gap:12px;">
                {msgs_content}
            </div>
        </div>""")

    steps_content = "\n".join(steps_html)

    started = run_log.get("started_at", "")
    if isinstance(started, (int, float)):
        started = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Workflow Run: {html_lib.escape(name)}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; max-width: 900px; margin: 0 auto; padding: 24px; line-height: 1.6; }}
    h1 {{ color: #f1f5f9; border-bottom: 1px solid #334155; padding-bottom: 12px; }}
    h2 {{ color: #cbd5e1; margin-top: 32px; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0; }}
    .meta-item {{ background: #1e293b; padding: 12px; border-radius: 6px; }}
    .meta-label {{ color: #94a3b8; font-size: 0.85em; }}
    .meta-value {{ color: #f1f5f9; font-weight: 600; font-size: 1.1em; }}
    .prompt {{ background: #1e293b; padding: 16px; border-radius: 8px; border-left: 3px solid #3b82f6; margin: 16px 0; white-space: pre-wrap; }}
    .msg {{ margin-bottom: 8px; }}
    pre {{ margin: 4px 0; }}
{WATERMARK_HTML_CSS}
</style>
</head>
<body>
{watermark_html_overlay()}
<h1>Workflow Run: {html_lib.escape(name)}</h1>
{watermark_html()}

<div class="meta">
    <div class="meta-item">
        <div class="meta-label">Status</div>
        <div class="meta-value" style="color:{status_color}">{html_lib.escape(status.upper())}</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Started</div>
        <div class="meta-value">{html_lib.escape(str(started))}</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Duration</div>
        <div class="meta-value">{duration:.1f}s</div>
    </div>
    <div class="meta-item">
        <div class="meta-label">Estimated Cost</div>
        <div class="meta-value">${cost:.4f}</div>
    </div>
</div>

<h2>Initial Prompt</h2>
<div class="prompt">{html_lib.escape(prompt)}</div>

<h2>Steps</h2>
{steps_content}

<h2>Summary</h2>
<p>{len(steps)} steps &middot; {duration:.1f}s &middot; ${cost:.4f}</p>
<p style="color:#64748b;font-size:0.85em;margin-top:32px;">Generated by Synapsis Analytics Agent</p>
</body>
</html>"""

    base = safe_filename(f"workflow_run_{name}_{run_id[:8] if run_id else 'unknown'}")
    filename = base + ".html"
    return html_content, filename
