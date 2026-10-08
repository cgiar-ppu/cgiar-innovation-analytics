"""
Tests for synapsis/database.py

Covers schema initialization, migrations, and the core CRUD helpers:
save_message, create_session, save/get_claude_session_id, load_memories_context.
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Schema / init_db tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_db_creates_all_tables(initialized_db: Path):
    """Verify that init_db creates all 5 required tables."""
    expected_tables = {"messages", "sessions", "memories", "workflows", "agents"}
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
    actual_tables = {row[0] for row in rows}
    assert expected_tables.issubset(actual_tables), (
        f"Missing tables: {expected_tables - actual_tables}"
    )


@pytest.mark.asyncio
async def test_init_db_creates_indexes(initialized_db: Path):
    """Verify that the expected indexes are created by init_db."""
    expected_indexes = {"idx_messages_session", "idx_memories_category", "idx_memories_importance"}
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        rows = await cursor.fetchall()
    actual_indexes = {row[0] for row in rows}
    assert expected_indexes.issubset(actual_indexes), (
        f"Missing indexes: {expected_indexes - actual_indexes}"
    )


@pytest.mark.asyncio
async def test_init_db_creates_fts_table(initialized_db: Path):
    """Verify that the memories_fts virtual FTS5 table is created."""
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        )
        row = await cursor.fetchone()
    assert row is not None, "memories_fts virtual table not found"


@pytest.mark.asyncio
async def test_init_db_idempotent(initialized_db: Path, tmp_path: Path):
    """Calling init_db a second time must not raise or corrupt the schema."""
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", tmp_path / ".synapsis"),
    ):
        from synapsis.database import init_db
        # Should not raise
        await init_db()

    # Tables should still be intact
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        )
        row = await cursor.fetchone()
    assert row[0] >= 5, "Tables disappeared after second init_db call"


@pytest.mark.asyncio
async def test_migration_step_configs_column(initialized_db: Path):
    """Verify that the step_configs column exists on the workflows table after init."""
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute("PRAGMA table_info(workflows)")
        columns = {row[1] for row in await cursor.fetchall()}
    assert "step_configs" in columns, "step_configs column missing from workflows table"


# ---------------------------------------------------------------------------
# save_message tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_message(initialized_db: Path, tmp_path: Path):
    """Insert a message via save_message and verify it is retrievable."""
    synapsis_dir = tmp_path / ".synapsis"
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None  # reset singleton for this test

        from synapsis.database import save_message, create_session, close_db

        session_id = "test-session-001"
        await create_session(session_id, title="Test Session")
        await save_message(session_id, "user", {"text": "hello world"})

        db = await db_module._get_shared_db()
        cursor = await db.execute(
            "SELECT type, data FROM messages WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        await close_db()

    assert row is not None, "Message was not saved"
    assert row[0] == "user"
    import json
    assert json.loads(row[1])["text"] == "hello world"


# ---------------------------------------------------------------------------
# create_session tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_session(initialized_db: Path, tmp_path: Path):
    """Create a session and verify all expected fields are present."""
    synapsis_dir = tmp_path / ".synapsis"
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None

        from synapsis.database import create_session, close_db

        await create_session("sess-abc", title="My Session")

        db = await db_module._get_shared_db()
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", ("sess-abc",)
        )
        row = await cursor.fetchone()
        await close_db()

    assert row is not None
    assert row["session_id"] == "sess-abc"
    assert row["title"] == "My Session"
    assert row["created_at"] > 0
    assert row["updated_at"] > 0


@pytest.mark.asyncio
async def test_create_session_ignore_duplicate(initialized_db: Path, tmp_path: Path):
    """INSERT OR IGNORE semantics: inserting the same session_id twice must not raise."""
    synapsis_dir = tmp_path / ".synapsis"
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None

        from synapsis.database import create_session, close_db

        await create_session("dup-session", title="First")
        # Second insert with same session_id should not raise
        await create_session("dup-session", title="Second")

        db = await db_module._get_shared_db()
        cursor = await db.execute(
            "SELECT count(*) FROM sessions WHERE session_id = ?", ("dup-session",)
        )
        row = await cursor.fetchone()
        await close_db()

    assert row[0] == 1, "Duplicate session was inserted; expected INSERT OR IGNORE to skip it"


# ---------------------------------------------------------------------------
# claude_session_id round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_get_claude_session_id(initialized_db: Path, tmp_path: Path):
    """Save a Claude SDK session UUID and read it back successfully."""
    synapsis_dir = tmp_path / ".synapsis"
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None

        from synapsis.database import (
            create_session, save_claude_session_id, get_claude_session_id, close_db
        )

        await create_session("app-sess-1", title="")
        await save_claude_session_id("app-sess-1", "claude-uuid-xyz")
        result = await get_claude_session_id("app-sess-1")
        await close_db()

    assert result == "claude-uuid-xyz"


# ---------------------------------------------------------------------------
# load_memories_context tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_memories_context_empty(initialized_db: Path, tmp_path: Path):
    """Returns an empty string when no active memories exist."""
    synapsis_dir = tmp_path / ".synapsis"
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None

        from synapsis.database import load_memories_context, close_db
        result = await load_memories_context()
        await close_db()

    assert result == "", f"Expected empty string, got: {result!r}"


@pytest.mark.asyncio
async def test_load_memories_context_with_data(initialized_db: Path, tmp_path: Path):
    """Returns a formatted string containing memory entries when memories exist."""
    synapsis_dir = tmp_path / ".synapsis"
    import time
    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.database.SYNAPSIS_DIR", synapsis_dir),
    ):
        import synapsis.database as db_module
        db_module._db = None

        # Insert a memory directly
        db = await db_module._get_shared_db()
        now = time.time()
        await db.execute(
            "INSERT INTO memories (category, content, importance, created_at, updated_at, active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            ("user_profile", "User prefers Python 3", 8, now, now),
        )
        await db.commit()

        from synapsis.database import load_memories_context, close_db
        result = await load_memories_context()
        await close_db()

    assert "user_profile" in result
    assert "User prefers Python 3" in result
    assert "[Persistent memories from previous sessions:]" in result


# ---------------------------------------------------------------------------
# Shared-connection write safety (L3-10): lock + rollback + WAL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shared_connection_uses_wal_and_busy_timeout(initialized_db: Path):
    import synapsis.database as db_module
    db = await db_module._get_shared_db()
    mode = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
    timeout_ms = (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0]
    assert mode.lower() == "wal"
    assert timeout_ms >= 1000


@pytest.mark.asyncio
async def test_shared_write_rolls_back_on_exception(initialized_db: Path):
    from synapsis.database import create_session
    from synapsis.database.connection import shared_write
    import synapsis.database as db_module

    await create_session("rb-exc", title="t")
    with pytest.raises(RuntimeError):
        async with shared_write() as db:
            await db.execute(
                "INSERT INTO messages (session_id, ts, type, data) VALUES ('rb-exc', 1, 'user', '{}')"
            )
            raise RuntimeError("boom")
    shared = await db_module._get_shared_db()
    assert not shared.in_transaction
    async with aiosqlite.connect(str(initialized_db)) as other:
        count = (await (await other.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='rb-exc'")).fetchone())[0]
    assert count == 0


@pytest.mark.asyncio
async def test_cancel_between_execute_and_commit_leaves_no_open_transaction(initialized_db: Path):
    """The 2026-09-10 incident pattern: a streaming task is cancelled after
    its INSERT but before COMMIT. The shared connection must not keep the
    write transaction open (it used to block every other writer ~30 s)."""
    import asyncio
    import time as _time
    from synapsis.database import create_session
    from synapsis.database.connection import shared_write
    import synapsis.database as db_module

    await create_session("rb-cancel", title="t")
    inserted = asyncio.Event()

    async def writer():
        async with shared_write() as db:
            await db.execute(
                "INSERT INTO messages (session_id, ts, type, data) VALUES ('rb-cancel', 1, 'user', '{}')"
            )
            inserted.set()
            await asyncio.sleep(10)  # cancelled here, before commit

    task = asyncio.create_task(writer())
    await inserted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    shared = await db_module._get_shared_db()
    assert not shared.in_transaction
    # Another connection can write immediately (no 30 s lock wait).
    start = _time.monotonic()
    async with aiosqlite.connect(str(initialized_db), timeout=2) as other:
        await other.execute("UPDATE sessions SET title='x' WHERE session_id='rb-cancel'")
        await other.commit()
        count = (await (await other.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='rb-cancel'")).fetchone())[0]
    assert _time.monotonic() - start < 1.5
    assert count == 0


@pytest.mark.asyncio
async def test_concurrent_save_message_calls_are_serialised(initialized_db: Path):
    import asyncio
    from synapsis.database import create_session, save_message

    await create_session("rb-many", title="t")
    await asyncio.gather(*(save_message("rb-many", "text", {"n": i}) for i in range(40)))
    async with aiosqlite.connect(str(initialized_db)) as db:
        msgs = (await (await db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='rb-many'")).fetchone())[0]
        mc = (await (await db.execute(
            "SELECT message_count FROM sessions WHERE session_id='rb-many'")).fetchone())[0]
    assert msgs == 40 and mc == 40
