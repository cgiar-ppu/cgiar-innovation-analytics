"""
synapsis.session -- session management package.

Re-exports all public names so that ``from synapsis.session import X`` works
identically to the old ``from synapsis.session_manager import X``.
"""

# Sub-modules
from synapsis.session.client_factory import create_client_with_retry
from synapsis.session.client_registry import ClientRegistry
from synapsis.session.connection_registry import ConnectionRegistry
from synapsis.session.broadcast import Broadcaster
from synapsis.session.cancel import CancelManager
from synapsis.session.manager import SessionManager

# Module-level singleton
session_manager = SessionManager()

# Expose the singleton's sessions dict at module level
sessions = session_manager.sessions


# ---------------------------------------------------------------------------
# Backward-compatible module-level wrappers
# ---------------------------------------------------------------------------

def has_active_connections() -> bool:
    return session_manager.has_active_connections()


def get_last_activity() -> float:
    return session_manager.get_last_activity()


def get_activity_stats() -> dict:
    return session_manager.get_activity_stats()


async def increment_connections() -> None:
    return await session_manager.increment_connections()


async def decrement_connections() -> None:
    return await session_manager.decrement_connections()


async def record_activity(ts: float) -> None:
    return await session_manager.record_activity(ts)


def get_session_lock(session_id: str):
    return session_manager.get_session_lock(session_id)


async def acquire_session_client(session_id: str, sessions_dict: dict):
    return await session_manager.acquire_session_client(session_id, sessions_dict)


def release_session_client(session_id: str) -> None:
    return session_manager.release_session_client(session_id)


def is_session_busy(session_id: str) -> bool:
    return session_manager.is_session_busy(session_id)


def cleanup_done_tasks(*args, **kwargs) -> None:
    return session_manager.cleanup_done_tasks(*args, **kwargs)


def register_connection(send_json_fn) -> None:
    return session_manager.register_connection(send_json_fn)


def unregister_connection(send_json_fn) -> None:
    return session_manager.unregister_connection(send_json_fn)


def register_session_viewer(session_id: str, send_json_fn) -> None:
    return session_manager.register_session_viewer(session_id, send_json_fn)


def unregister_session_viewer(session_id: str, send_json_fn) -> None:
    return session_manager.unregister_session_viewer(session_id, send_json_fn)


async def broadcast_to_session(session_id: str, message: dict, *, exclude=None) -> None:
    return await session_manager.broadcast_to_session(session_id, message, exclude=exclude)


async def broadcast_to_all(message: dict, *, exclude=None) -> None:
    return await session_manager.broadcast_to_all(message, exclude=exclude)


async def cleanup_session_client(session_id: str) -> None:
    return await session_manager.cleanup_session_client(session_id)


async def cleanup_orphaned_sessions() -> int:
    return await session_manager.cleanup_orphaned_sessions()


async def handle_new_session(sessions_dict: dict, send_json):
    return await session_manager.handle_new_session(sessions_dict, send_json)


async def handle_switch_session(payload: dict, sessions_dict: dict, send_json):
    return await session_manager.handle_switch_session(payload, sessions_dict, send_json)


async def ensure_session(session_id, user_message: str, sessions_dict: dict):
    return await session_manager.ensure_session(session_id, user_message, sessions_dict)


async def cancel_existing_task(session_id) -> None:
    return await session_manager.cancel_existing_task(session_id)


async def handle_cancel(session_id, client, sessions_dict: dict, send_json) -> None:
    return await session_manager.handle_cancel(
        session_id, client, sessions_dict, send_json,
    )


__all__ = [
    # Classes
    "SessionManager",
    "ClientRegistry",
    "ConnectionRegistry",
    "Broadcaster",
    "CancelManager",
    # Singleton
    "session_manager",
    "sessions",
    # Functions
    "create_client_with_retry",
    "has_active_connections",
    "get_last_activity",
    "get_activity_stats",
    "increment_connections",
    "decrement_connections",
    "record_activity",
    "get_session_lock",
    "acquire_session_client",
    "release_session_client",
    "is_session_busy",
    "cleanup_done_tasks",
    "register_connection",
    "unregister_connection",
    "register_session_viewer",
    "unregister_session_viewer",
    "broadcast_to_session",
    "broadcast_to_all",
    "cleanup_session_client",
    "cleanup_orphaned_sessions",
    "handle_new_session",
    "handle_switch_session",
    "ensure_session",
    "cancel_existing_task",
    "handle_cancel",
]
