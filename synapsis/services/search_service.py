"""
Search business logic — pure functions extracted from route handlers.
"""

from __future__ import annotations


def extract_search_snippets(messages: list[dict], query: str) -> list[dict]:
    """Extract matching snippets from a list of messages.

    For each message whose ``content`` contains *query* (case-insensitive),
    a snippet with surrounding context (~60 chars each side) is returned.

    This is a pure function with no DB or HTTP dependency; the caller is
    responsible for fetching messages and enriching results with session
    titles or timestamps.

    Args:
        messages: Sequence of dicts, each with at least ``content`` (str),
            ``session_id``, and ``message_type`` keys.
        query: The search term (non-empty).

    Returns:
        A list of result dicts with keys ``session_id``, ``message_type``,
        and ``snippet``.  Only messages that actually contain the query are
        included.
    """
    lower_q = query.lower()
    results: list[dict] = []

    for msg in messages:
        content = msg.get("content", "")
        lower_content = content.lower()
        idx = lower_content.find(lower_q)
        if idx == -1:
            continue

        # Extract snippet with surrounding context.
        start = max(0, idx - 60)
        end = min(len(content), idx + len(query) + 60)
        snippet = content[start:end]
        if start > 0:
            snippet = "\u2026" + snippet
        if end < len(content):
            snippet = snippet + "\u2026"

        results.append({
            "session_id": msg["session_id"],
            "message_type": msg["message_type"],
            "snippet": snippet,
        })

    return results
