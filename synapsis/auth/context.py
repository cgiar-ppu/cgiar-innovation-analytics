"""
Per-request / per-connection identity context (July-7 Step 4).

The WebSocket chat path creates sessions deep inside the session-manager /
client-registry call chain, far from where the authenticated identity is known.
Rather than thread a ``user_id`` argument through every intermediate function
(high regression surface), the authenticated identity is stashed in a
``contextvars.ContextVar`` at connection time and read at session-creation time.

``contextvars`` is async-task-safe: each WebSocket connection runs in its own
task tree, and each task inherits an independent copy of the context, so
concurrent users never see each other's identity.

NOTE (honest-limitation, see docs/SECURITY-SCOPING-NOTE.md): this identity
scopes the *chat list and history* per user. It does NOT sandbox agent
execution — the agent still runs in a shared workspace.

Admin-legacy-chat exception (2026-07-19/20): the WS path also carries the
verified ``role`` claim alongside ``user_id`` (never client-suppliable —
always the role decoded from the JWT), so ``switch_session`` can grant admins
visibility into sentinel-owned sessions via
``synapsis.auth.scoping.is_visible_to``. This does NOT affect creation
attribution: new sessions are always created under ``user_id``, never role.
"""

from contextvars import ContextVar
from typing import Optional

from synapsis.config import LEGACY_USER_ID

# The current connection/request's owning user_id. Defaults to the legacy
# sentinel so anything created outside an authenticated context (e.g. workflow
# continuation sessions) is attributed to the sentinel, never to a real user.
_current_user_id: ContextVar[str] = ContextVar("current_user_id", default=LEGACY_USER_ID)

# The current connection's verified role claim (admin/researcher/user/...).
# Defaults to "user" -- the least-privileged role -- so a context that never
# calls set_current_user_id() (e.g. a background task) never gains admin
# visibility by accident.
_current_role: ContextVar[str] = ContextVar("current_role", default="user")


def set_current_user_id(user_id: Optional[str], role: Optional[str] = None) -> None:
    """Set the owning user_id (and optionally role) for the current async context.

    ``role`` is optional and backward-compatible: existing callers that only
    pass ``user_id`` are unaffected and the role contextvar simply keeps its
    default ("user").
    """
    _current_user_id.set(user_id or LEGACY_USER_ID)
    if role is not None:
        _current_role.set(role)


def get_current_user_id() -> str:
    """Return the owning user_id for the current async context."""
    return _current_user_id.get()


def get_current_role() -> str:
    """Return the verified role for the current async context."""
    return _current_role.get()
