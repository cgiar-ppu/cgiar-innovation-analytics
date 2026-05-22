"""
Shared response-building helpers for MCP tool handlers.

All tools return dicts with a ``content`` list of typed blocks. These helpers
enforce a consistent shape so callers never hand-roll the same structure.
"""


def error_response(message: str) -> dict:
    """Return a structured tool error response."""
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def success_response(message: str) -> dict:
    """Return a structured tool success response."""
    return {"content": [{"type": "text", "text": message}]}
