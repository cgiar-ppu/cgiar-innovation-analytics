"""
Shared helpers used by multiple exporter modules.

- parse_row: decode a raw DB row into (msg_type, data dict, formatted timestamp)
- is_visible: which rows a 'standard' / 'full' export shows
- safe_filename: build a filesystem-safe filename from a session title
"""

import json
import re
from datetime import datetime, timezone


def parse_row(row) -> tuple[str, dict, str]:
    """Decode a raw DB message row into (msg_type, data, formatted_ts).

    The timestamp carries the date and an explicit UTC zone (review L6-14: a
    bare ``HH:MM`` in the container's zone was ambiguous in a shared export).
    """
    data = json.loads(row["data"])
    msg_type = row["type"]
    ts = datetime.fromtimestamp(row["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return msg_type, data, ts


def is_visible(msg_type: str, data: dict, detail: str) -> bool:
    """Whether a row appears in an export of the given *detail* level.

    'standard' (what users share outside the app) shows the conversation only:
    the user's questions, the assistant's answers and file-upload notes. Tool
    calls, tool results, thinking, other system notices and the per-turn
    "N turns · Xs" line are internal and appear only in 'full' exports.
    """
    if msg_type in ("user", "text"):
        return True
    if msg_type == "system" and data.get("subtype") == "file_upload":
        return True
    return detail == "full"


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
