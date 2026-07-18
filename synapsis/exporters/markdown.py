"""
Markdown exporter — converts session rows to a .md document.
"""

import json
from datetime import datetime

from .common import parse_row
from .watermark import watermark_markdown


def export_markdown(title: str, session_id: str, rows, detail: str) -> tuple[str, str]:
    """Convert messages to Markdown format.

    Args:
        title:      Human-readable session title.
        session_id: Session UUID used in the header.
        rows:       Iterable of raw DB message rows (type, data JSON, ts).
        detail:     'standard' or 'full'. 'full' includes thinking blocks,
                    tool inputs/outputs, and non-file-upload system messages.

    Returns:
        (content, media_type) where content is the rendered Markdown string.
    """
    lines = [f"# {title}\n"]
    # AI-content watermark / disclaimer — required at the top of every export.
    lines.append(watermark_markdown())
    lines.append(f"\n*Exported on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    lines.append(f"*Session: {session_id}*\n\n---\n")

    for row in rows:
        msg_type, data, ts = parse_row(row)

        if msg_type == "user":
            lines.append(f"\n## 🧑 You ({ts})\n\n{data.get('content', '')}\n")

        elif msg_type == "text":
            lines.append(f"\n## 🤖 Assistant ({ts})\n\n{data.get('content', '')}\n")

        elif msg_type == "system":
            subtype = data.get("subtype", "")
            content = data.get("content", "")
            if subtype == "file_upload":
                lines.append(f"\n📎 *{content}*\n")
            elif detail == "full":
                lines.append(f"\n> 📋 **System** `{subtype}`\n> {content}\n")

        elif msg_type == "thinking" and detail == "full":
            content = data.get("content", "")
            quoted = "\n".join(f"> {line}" for line in content.splitlines())
            lines.append(f"\n> 💭 **Thinking**\n{quoted}\n")

        elif msg_type == "tool_use":
            tool_name = data.get("tool", "unknown")
            if detail == "full":
                input_json = json.dumps(data.get("input", {}), indent=2)
                input_quoted = "\n".join(f"> {line}" for line in input_json.splitlines())
                lines.append(f"\n> 🔧 **Tool: {tool_name}**\n> ```json\n{input_quoted}\n> ```\n")
            else:
                lines.append(f"\n> 🔧 **Tool: {tool_name}**\n")

        elif msg_type == "tool_result" and detail == "full":
            content = str(data.get("content", ""))[:2000]
            quoted = "\n".join(f"> {line}" for line in content.splitlines())
            lines.append(f"\n> 📤 **Result**\n{quoted}\n")

        elif msg_type == "result":
            turns = data.get("turns", 0)
            duration = data.get("duration_ms", 0)
            lines.append(f"\n---\n*{turns} turns · {duration/1000:.1f}s*\n")

    return "\n".join(lines), "text/markdown"
