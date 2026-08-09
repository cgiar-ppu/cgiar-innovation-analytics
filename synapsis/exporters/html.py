"""
HTML exporter — produces a self-contained, styled HTML document from session rows.
"""

import html as html_module
import json
from datetime import datetime

from .common import parse_row
from .watermark import watermark_html, watermark_html_overlay, WATERMARK_HTML_CSS

# ---------------------------------------------------------------------------
# Inline CSS — extracted here so the render function stays readable
# ---------------------------------------------------------------------------
_STYLES = """\
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; line-height: 1.6; }
  h1 { color: #2e7d32; border-bottom: 2px solid #2e7d32; padding-bottom: 0.5rem; }
  .meta { color: #666; font-size: 0.85rem; margin-bottom: 2rem; }
  .message { margin: 1.5rem 0; padding: 1rem; border-radius: 12px; }
  .user { background: #e8f5e9; border-left: 4px solid #2e7d32; }
  .assistant { background: #f5f5f5; border-left: 4px solid #1565c0; }
  .role { font-weight: 600; font-size: 0.85rem; margin-bottom: 0.5rem; }
  .user .role { color: #2e7d32; }
  .assistant .role { color: #1565c0; }
  .tool { background: #fff3e0; border-left: 4px solid #e65100; padding: 0.5rem 1rem; margin: 0.5rem 0; font-size: 0.85rem; border-radius: 6px; }
  .result { text-align: center; color: #666; font-size: 0.8rem; padding: 0.5rem; border-top: 1px solid #ddd; margin-top: 1.5rem; }
  .thinking { background: #f3e5f5; border-left: 4px solid #7b1fa2; padding: 0.5rem 1rem; margin: 0.5rem 0; font-size: 0.85rem; border-radius: 6px; color: #4a148c; }
  .tool-detail { background: #fff3e0; border-left: 4px solid #e65100; padding: 0.5rem 1rem; margin: 0.5rem 0; font-size: 0.85rem; border-radius: 6px; }
  .tool-result { background: #e8eaf6; border-left: 4px solid #283593; padding: 0.5rem 1rem; margin: 0.5rem 0; font-size: 0.85rem; border-radius: 6px; }
  .file-upload { background: #e8f5e9; padding: 0.3rem 0.8rem; margin: 0.5rem 0; font-size: 0.85rem; border-radius: 20px; display: inline-block; color: #2e7d32; }
  pre { background: #263238; color: #eee; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; }
  code { background: #e0e0e0; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.9em; }
  pre code { background: none; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }
  th { background: #f5f5f5; }
  blockquote { border-left: 4px solid #2e7d32; margin: 1rem 0; padding: 0.5rem 1rem; color: #555; background: #f9f9f9; }"""


def export_html(title: str, session_id: str, rows, detail: str) -> tuple[str, str]:
    """Convert messages to a self-contained HTML document.

    Args:
        title:      Human-readable session title.
        session_id: Session UUID displayed in the page header.
        rows:       Iterable of raw DB message rows (type, data JSON, ts).
        detail:     'standard' or 'full'. 'full' includes thinking blocks,
                    tool inputs/outputs, and non-file-upload system messages.

    Returns:
        (content, media_type) where content is the rendered HTML string.
    """
    safe_title = html_module.escape(title)
    exported_at = datetime.now().strftime('%Y-%m-%d %H:%M')

    parts = [f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{safe_title}</title>
<style>
{_STYLES}
{WATERMARK_HTML_CSS}
</style>
</head>
<body>
{watermark_html_overlay()}
<h1>{safe_title}</h1>
{watermark_html()}
<div class="meta">Session: {session_id} · Exported: {exported_at}</div>
"""]

    for row in rows:
        msg_type, data, ts = parse_row(row)

        if msg_type == "user":
            content = html_module.escape(data.get("content", ""))
            parts.append(
                f'<div class="message user">'
                f'<div class="role">🧑 You · {ts}</div>'
                f'<div>{content}</div></div>'
            )

        elif msg_type == "text":
            content = html_module.escape(data.get("content", "")).replace("\n", "<br>")
            parts.append(
                f'<div class="message assistant">'
                f'<div class="role">🤖 Assistant · {ts}</div>'
                f'<div>{content}</div></div>'
            )

        elif msg_type == "system":
            subtype = data.get("subtype", "")
            content = html_module.escape(data.get("content", ""))
            if subtype == "file_upload":
                parts.append(f'<div class="file-upload">📎 {content}</div>')
            elif detail == "full":
                parts.append(
                    f'<div class="tool">📋 <strong>System</strong> '
                    f'<code>{html_module.escape(subtype)}</code>: {content}</div>'
                )

        elif msg_type == "thinking" and detail == "full":
            content = html_module.escape(data.get("content", "")).replace("\n", "<br>")
            parts.append(
                f'<div class="thinking">💭 <strong>Thinking</strong><br>{content}</div>'
            )

        elif msg_type == "tool_use":
            tool_name = html_module.escape(data.get("tool", "unknown"))
            if detail == "full":
                input_json = html_module.escape(json.dumps(data.get("input", {}), indent=2))
                parts.append(
                    f'<div class="tool-detail">🔧 <strong>Tool: {tool_name}</strong>'
                    f'<br><pre>{input_json}</pre></div>'
                )
            else:
                parts.append(f'<div class="tool">🔧 Tool: <strong>{tool_name}</strong></div>')

        elif msg_type == "tool_result" and detail == "full":
            content = html_module.escape(str(data.get("content", ""))[:2000]).replace("\n", "<br>")
            parts.append(
                f'<div class="tool-result">📤 <strong>Result</strong><br>{content}</div>'
            )

        elif msg_type == "result":
            turns = data.get("turns", 0)
            duration = data.get("duration_ms", 0)
            parts.append(f'<div class="result">{turns} turns · {duration/1000:.1f}s</div>')

    parts.append("</body></html>")
    return "\n".join(parts), "text/html"
