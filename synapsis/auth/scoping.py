"""
Centralized session-visibility scoping helper.

Admin-legacy-chat exception (2026-07-19/20)
--------------------------------------------
The ``user_id`` migration (``database/schema.py``) attributed every pre-auth
session to the sentinel ``LEGACY_USER_ID``. Strict per-user ``user_id = ?``
filtering (July-7 Step 4) therefore hides that entire pre-login history from
everyone, including admins, who reasonably expect to still see it.

Rather than scatter ``if role == "admin": ...`` checks across every route and
the WebSocket handler, every place that used to filter ``user_id = ?`` should
instead compute the list of ids it may see via :func:`allowed_user_ids` and
filter ``user_id IN (...)``, or check single-session visibility via
:func:`is_visible_to`. This is the ONE place the exception lives; a future
change to the policy (a new role, a different exception) only needs to change
here.

See ``docs/SECURITY-SCOPING-NOTE.md`` for the full write-up.
"""

from synapsis.config import LEGACY_USER_ID

ADMIN_ROLE = "admin"


def allowed_user_ids(user_id: str, role: str | None) -> list[str]:
    """Return the list of ``user_id`` values *user_id* (with *role*) may see.

    - Non-admin roles (or a missing/unknown role): own sessions only ->
      ``[user_id]``.
    - Admin role: own sessions PLUS the pre-auth sentinel's sessions ->
      ``[user_id, LEGACY_USER_ID]`` (deduped, in case ``user_id`` already IS
      the sentinel, e.g. dev-bypass mode).

    IMPORTANT: this only widens *visibility*. It does NOT change *creation*
    attribution -- new sessions created by an admin are still owned by that
    admin's own ``user_id`` (see ``database/sessions.py::create_session``),
    never silently re-attributed to the sentinel.
    """
    if role == ADMIN_ROLE:
        ids = [user_id]
        if LEGACY_USER_ID not in ids:
            ids.append(LEGACY_USER_ID)
        return ids
    return [user_id]


def is_visible_to(owner: str | None, user_id: str, role: str | None) -> bool:
    """True if a session owned by *owner* is visible to *user_id* (with *role*).

    A falsy/``None`` owner (should not occur post-migration, but predates it
    defensively) is treated as visible to any authenticated caller -- this
    matches the original pre-admin-exception behavior of the owner check.
    """
    if not owner:
        return True
    return owner in allowed_user_ids(user_id, role)
