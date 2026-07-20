"""Synapsis database layer -- SQLite persistence for messages, sessions, and memories.

This package replaces the former monolithic ``database.py`` module.  All public
functions are re-exported here so existing imports like
``from synapsis.database import get_db`` continue to work unchanged.
"""

# -- Connection management ---------------------------------------------------
from synapsis.database.connection import (  # noqa: F401
    get_db,
    _get_shared_db,
    close_db,
    _manager,
)

# -- Schema ------------------------------------------------------------------
from synapsis.database.schema import init_db  # noqa: F401

# -- Message CRUD ------------------------------------------------------------
from synapsis.database.messages import save_message  # noqa: F401

# -- Session CRUD ------------------------------------------------------------
from synapsis.database.sessions import (  # noqa: F401
    create_session,
    get_session_owner,
    save_claude_session_id,
    get_claude_session_id,
    save_initial_context,
    consume_initial_context,
    get_session_model,
    update_session_model,
)

# -- Task status -------------------------------------------------------------
from synapsis.database.tasks import (  # noqa: F401
    update_session_task_status,
    get_session_task_status,
)

# -- Memory ------------------------------------------------------------------
from synapsis.database.memory import load_memories_context  # noqa: F401

# -- Users (interim self-signup) ----------------------------------------------
from synapsis.database.users import (  # noqa: F401
    init_users_table,
    get_user_row,
    create_user_row,
    list_user_rows,
)

# -- History index -----------------------------------------------------------
from synapsis.database.history import (  # noqa: F401
    init_history_tables,
    index_session,
    index_all_sessions,
    search_history,
    retrieve_conversation,
    list_indexed_sessions,
)

# -- Re-export config values that tests and conftest patch on this module ----
from synapsis.config import DB_PATH, SYNAPSIS_DIR  # noqa: F401

# ---------------------------------------------------------------------------
# Backward-compat: tests reference ``synapsis.database._db`` directly to
# reset the shared singleton.  Expose the _manager's internal ``_db`` as a
# module-level attribute via __getattr__ / __setattr__-style property.
# ---------------------------------------------------------------------------

def __getattr__(name: str):
    if name == "_db":
        return _manager._db
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
