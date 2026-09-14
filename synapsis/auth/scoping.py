"""Own-chat visibility for every role; pre-login history is retained but private.

Jose's 2026-09-14 ruling removes the former administrator exception. Missing
ownership fails closed. Administrative account privileges never grant chat access.
"""

def allowed_user_ids(user_id: str, role: str | None) -> list[str]:
    """Roles do not widen chat visibility; local bypass keeps its own sentinel."""
    return [user_id] if user_id else []


def is_visible_to(owner: str | None, user_id: str, role: str | None) -> bool:
    """Only a nonempty, exact owner match grants access."""
    return bool(owner and user_id and owner == user_id)
