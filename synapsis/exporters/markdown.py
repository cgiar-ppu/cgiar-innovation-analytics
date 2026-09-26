"""
Markdown exporter — converts session rows to a .md document.

The answers are already Markdown, so they are kept as written, with three
export-time fixes (see :mod:`synapsis.exporters.render`): result codes are
linked to their public PRMS report, server file paths are reduced to the file
name, and ``<chart>`` JSON blocks become a captioned Markdown table.
"""

import json
from datetime import datetime

from .common import is_visible, parse_row
from .render import (
    clean_text,
    prepare_assistant_text,
    prepare_user_text,
    replace_charts_with_markdown_tables,
)
from .watermark import watermark_markdown, watermark_markdown_footer


def export_markdown(title: str, session_id: str, rows, detail: str) -> tuple[str, str]:
    """Convert messages to Markdown format.

    Args:
        title:      Human-readable session title.
        session_id: Session UUID used in the header.
        rows:       Iterable of raw DB message rows (type, data JSON, ts).
        detail:     'standard' or 'full'. 'standard' is the conversation only
                    (questions, answers, file uploads); 'full' also includes
                    thinking blocks, tool inputs/outputs, system messages and
                    the per-turn statistics.

    Returns:
        (content, media_type) where content is the rendered Markdown string.
    """
    lines = [f"# {clean_text(title)}\n"]
    # AI-content watermark / disclaimer — required at the top of every export.
    lines.append(watermark_markdown())
    lines.append(f"\n*Exported on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    lines.append(f"*Session: {session_id}*\n\n---\n")

    for row in rows:
        msg_type, data, ts = parse_row(row)
        if not is_visible(msg_type, data, detail):
            continue

        if msg_type == "user":
            lines.append(f"\n## 🧑 You ({ts})\n\n{prepare_user_text(data.get('content', ''))}\n")

        elif msg_type == "text":
            body = replace_charts_with_markdown_tables(prepare_assistant_text(data.get("content", "")))
            lines.append(f"\n## 🤖 Assistant ({ts})\n\n{body}\n")

        elif msg_type == "system":
            subtype = data.get("subtype", "")
            content = prepare_user_text(data.get("content", ""))
            if subtype == "file_upload":
                lines.append(f"\n📎 *{content}*\n")
            else:
                lines.append(f"\n> 📋 **System** `{subtype}`\n> {content}\n")

        elif msg_type == "thinking":
            content = clean_text(data.get("content", ""))
            quoted = "\n".join(f"> {line}" for line in content.splitlines())
            lines.append(f"\n> 💭 **Thinking**\n{quoted}\n")

        elif msg_type == "tool_use":
            tool_name = data.get("tool", "unknown")
            input_json = clean_text(json.dumps(data.get("input", {}), indent=2))
            input_quoted = "\n".join(f"> {line}" for line in input_json.splitlines())
            lines.append(f"\n> 🔧 **Tool: {tool_name}**\n> ```json\n{input_quoted}\n> ```\n")

        elif msg_type == "tool_result":
            content = clean_text(str(data.get("content", ""))[:2000])
            quoted = "\n".join(f"> {line}" for line in content.splitlines())
            lines.append(f"\n> 📤 **Result**\n{quoted}\n")

        elif msg_type == "result":
            turns = data.get("turns", 0)
            duration = data.get("duration_ms", 0)
            lines.append(f"\n---\n*{turns} turns · {duration/1000:.1f}s*\n")

    # Per-page-footer analogue for a format with no pages: close the document
    # with the product line + banner + provenance notice.
    lines.append(watermark_markdown_footer())

    return "\n".join(lines), "text/markdown"
