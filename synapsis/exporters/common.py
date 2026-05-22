"""
Shared helpers used by multiple exporter modules.

- parse_row: decode a raw DB row into (msg_type, data dict, formatted timestamp)
- safe_filename: build a filesystem-safe filename from a session title
"""

import json
import re
from datetime import datetime


def parse_row(row) -> tuple[str, dict, str]:
    """Decode a raw DB message row into (msg_type, data, formatted_ts)."""
    data = json.loads(row["data"])
    msg_type = row["type"]
    ts = datetime.fromtimestamp(row["ts"]).strftime("%H:%M")
    return msg_type, data, ts


def safe_filename(title: str, session_id: str = "", ext: str = "") -> str:
    """Generate a filesystem-safe filename from a title.

    Args:
        title:      Human-readable title (or full base name when called without ext).
        session_id: Optional session/run ID appended after the title.
        ext:        Optional file extension (without leading dot).

    When called with all three arguments the result is ``{title}_{session_id}.{ext}``.
    When called with only *title* the result is the sanitized title string (the
    caller is expected to append the extension themselves).
    """
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    if session_id and ext:
        return f"{safe_title}_{session_id}.{ext}"
    if session_id:
        return f"{safe_title}_{session_id}"
    return safe_title
