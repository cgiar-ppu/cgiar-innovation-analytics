"""
Session manager -- backward-compatible re-export shim.

All implementation has moved to the ``synapsis.session`` package.  This module
re-exports every public name so that existing callers like::

    from synapsis.session_manager import broadcast_to_all

continue to work unchanged.
"""

from synapsis.session import (  # noqa: F401
    # Classes
    SessionManager,
    ClientRegistry,
    ConnectionRegistry,
    Broadcaster,
    CancelManager,
    # Singleton & state
    session_manager,
    sessions,
    # Standalone function
    create_client_with_retry,
    # Module-level wrappers
    has_active_connections,
    get_last_activity,
    get_activity_stats,
    increment_connections,
    decrement_connections,
    record_activity,
    get_session_lock,
    acquire_session_client,
    release_session_client,
    is_session_busy,
    cleanup_done_tasks,
    register_connection,
    unregister_connection,
    register_session_viewer,
    unregister_session_viewer,
    broadcast_to_session,
    broadcast_to_all,
    cleanup_session_client,
    cleanup_orphaned_sessions,
    handle_new_session,
    handle_switch_session,
    ensure_session,
    cancel_existing_task,
    handle_cancel,
)
