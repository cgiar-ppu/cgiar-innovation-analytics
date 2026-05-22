"""
Shared message visitor pattern for session exporters.

Centralises the if/elif dispatch on message type so that each exporter
only implements format-specific rendering logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from .common import parse_row


class MessageVisitor(Protocol):
    """Protocol that each exporter implements for format-specific rendering.

    Every ``visit_*`` method receives the parsed *data* dict and the
    formatted timestamp so it can pull out whatever fields it needs.
    Returning ``None`` signals "skip this message" (e.g. when *detail*
    is not ``'full'``).
    """

    def visit_user(self, data: dict, ts: str) -> Any: ...
    def visit_text(self, data: dict, ts: str) -> Any: ...
    def visit_system(self, data: dict, ts: str) -> Any: ...
    def visit_thinking(self, data: dict, ts: str) -> Any: ...
    def visit_tool_use(self, data: dict, ts: str) -> Any: ...
    def visit_tool_result(self, data: dict, ts: str) -> Any: ...
    def visit_result(self, data: dict, ts: str) -> Any: ...


_DISPATCH = {
    "user": "visit_user",
    "text": "visit_text",
    "system": "visit_system",
    "thinking": "visit_thinking",
    "tool_use": "visit_tool_use",
    "tool_result": "visit_tool_result",
    "result": "visit_result",
}


def visit_messages(rows, visitor: MessageVisitor) -> list[Any]:
    """Iterate raw DB rows, dispatch each to *visitor*, collect non-None results.

    Args:
        rows:    Iterable of raw DB message rows (as returned by the session
                 query).  Each row is decoded via :func:`common.parse_row`.
        visitor: An object implementing the :class:`MessageVisitor` protocol.

    Returns:
        List of non-``None`` values returned by the visitor methods.
    """
    results: list[Any] = []
    for row in rows:
        msg_type, data, ts = parse_row(row)
        method_name = _DISPATCH.get(msg_type)
        if method_name is None:
            continue
        result = getattr(visitor, method_name)(data, ts)
        if result is not None:
            results.append(result)
    return results
