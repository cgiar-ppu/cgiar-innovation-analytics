"""Schema initialization and migrations for the main chat database.

Contains all CREATE TABLE statements and incremental ALTER TABLE migrations.
"""

import aiosqlite

import synapsis.config as _config
from synapsis.config import logger
from synapsis.database.connection import get_db


async def init_db() -> None:
    """Create tables and indexes if they don't exist.

    Tables:
    - messages:  Chat messages (user, assistant, tool_use, tool_result, thinking, result)
    - sessions:  Chat sessions with metadata and Claude SDK session ID for resumption
    - memories:  Persistent memories with FTS5 full-text search index

    Also runs any incremental migrations needed to bring an existing schema
    up to date (e.g. adding the ``claude_session_id`` column).
    """
    _config.SYNAPSIS_DIR.mkdir(parents=True, exist_ok=True)

    # Use a short-lived connection for schema setup so we don't pollute the
    # shared singleton before it is properly initialized.
    async with get_db() as db:
        # -- Messages table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                ts REAL NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages (session_id, ts)
        """)

        # -- Sessions table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                model TEXT DEFAULT '',
                message_count INTEGER DEFAULT 0,
                claude_session_id TEXT DEFAULT ''
            )
        """)

        # Migration: add claude_session_id column if missing (existing DBs)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN claude_session_id TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            logger.debug("claude_session_id column already exists — skipping migration")

        # Migration: add pinned column if missing (existing DBs)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            logger.debug("pinned column already exists — skipping migration")

        # Migration: add initial_context column for workflow continuation sessions
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN initial_context TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            logger.debug("initial_context column already exists — skipping migration")

        # -- Memories table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 5,
                source_session TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                tags TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories (category, active)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_importance
            ON memories (importance DESC, active)
        """)

        # -- Full-text search for memories --
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        )
        if not await cursor.fetchone():
            await db.execute("""
                CREATE VIRTUAL TABLE memories_fts USING fts5(
                    content, tags,
                    content='memories',
                    content_rowid='id'
                )
            """)

        # -- Workflows table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'draft',
                progress INTEGER DEFAULT 0,
                steps INTEGER DEFAULT 0,
                agent_sequence TEXT DEFAULT '[]',
                initial_prompt TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                created_at REAL,
                updated_at REAL,
                run_count INTEGER DEFAULT 0,
                last_run REAL
            )
        """)

        # -- Agents table (custom user-defined agents) --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                tools TEXT DEFAULT '[]',
                model TEXT DEFAULT 'sonnet',
                color TEXT DEFAULT '#6366f1',
                type TEXT DEFAULT 'custom',
                is_active INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL,
                created_by TEXT DEFAULT '',
                parent_agent TEXT DEFAULT '',
                version INTEGER DEFAULT 1
            )
        """)

        # Migration: add step_configs column to workflows if missing
        try:
            await db.execute("ALTER TABLE workflows ADD COLUMN step_configs TEXT DEFAULT '[]'")
        except aiosqlite.OperationalError:
            logger.debug("step_configs column already exists — skipping migration")

        # Migration: add task_status column to sessions if missing
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN task_status TEXT DEFAULT 'idle'")
        except aiosqlite.OperationalError:
            logger.debug("task_status column already exists — skipping migration")

        # Migration: add user_id column for per-user chat scoping (July-7 Step 4).
        # Idempotent: existing (pre-auth) sessions default to the legacy sentinel
        # so they are never silently attributed to a real user. New sessions are
        # created with the authenticated identity (see database/sessions.py).
        from synapsis.config import LEGACY_USER_ID
        try:
            await db.execute(
                f"ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT '{LEGACY_USER_ID}'"
            )
            # Backfill any pre-existing NULLs from before the column had a default.
            await db.execute(
                "UPDATE sessions SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
                (LEGACY_USER_ID,),
            )
            logger.info("Migrated sessions.user_id (legacy rows -> %s)", LEGACY_USER_ID)
        except aiosqlite.OperationalError:
            logger.debug("user_id column already exists — skipping migration")

        # Index to keep per-user chat-list queries fast.
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, updated_at)"
        )

        await db.commit()

    # -- History index tables (separate function to keep init_db focused) --
    from synapsis.database.history import init_history_tables
    await init_history_tables()

    # -- Users table (persistent, self-signup-capable; separate function to
    # keep init_db focused). Idempotent: creates the table if missing and
    # seeds/upserts baked-in allow-list accounts without ever overwriting an
    # existing row's password hash.
    from synapsis.database.users import init_users_table
    await init_users_table()
