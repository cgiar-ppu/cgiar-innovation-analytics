"""Tests for the chat history indexing, search, and retrieval system."""

import json
import time

import pytest

from synapsis.database import get_db
from synapsis.database.history import (
    init_history_tables,
    index_session,
    index_all_sessions,
    search_history,
    retrieve_conversation,
    list_indexed_sessions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_session(session_id: str, messages: list[tuple[str, str]]):
    """Insert a session and its messages into the database."""
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at, model, message_count) "
            "VALUES (?, '', ?, ?, 'opus', ?)",
            (session_id, now, now, len(messages)),
        )
        for i, (msg_type, content) in enumerate(messages):
            data = json.dumps({"content": content})
            await db.execute(
                "INSERT INTO messages (session_id, ts, type, data) VALUES (?, ?, ?, ?)",
                (session_id, now + i * 0.01, msg_type, data),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# Tests — all use initialized_db fixture for isolation
# ---------------------------------------------------------------------------

class TestHistoryTables:
    """Test history table creation."""

    async def test_init_creates_tables(self, initialized_db):
        """init_history_tables creates history_sessions, history_chunks, and history_fts."""
        async with get_db() as db:
            for table in ("history_sessions", "history_chunks", "history_fts"):
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                row = await cursor.fetchone()
                assert row is not None, f"Table {table} should exist"

    async def test_init_is_idempotent(self, initialized_db):
        """Calling init_history_tables twice should not raise."""
        await init_history_tables()
        await init_history_tables()


class TestIndexSession:
    """Test single-session indexing."""

    async def test_index_session_basic(self, initialized_db):
        """Index a session with user and assistant messages."""
        await _seed_session("test-001", [
            ("user", "What is the capital of France?"),
            ("text", "The capital of France is Paris."),
            ("tool_use", '{"tool": "search"}'),
            ("tool_result", '{"result": "Paris"}'),
            ("user", "Thanks!"),
        ])

        result = await index_session("test-001")
        assert result["session_id"] == "test-001"
        assert result["message_count"] == 3  # 2 user + 1 text, tool_use/tool_result skipped
        assert result["clean_text_length"] > 0

    async def test_index_session_nonexistent(self, initialized_db):
        """Indexing a nonexistent session returns error."""
        result = await index_session("nonexistent")
        assert "error" in result

    async def test_index_session_reindex(self, initialized_db):
        """Re-indexing a session replaces old data."""
        await _seed_session("test-002", [
            ("user", "Hello world"),
            ("text", "Hi there"),
        ])
        result1 = await index_session("test-002")
        assert result1["message_count"] == 2

        # Re-index
        result2 = await index_session("test-002")
        assert result2["message_count"] == 2

        # Check no duplicate entries
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM history_chunks WHERE session_id = 'test-002'"
            )
            row = await cursor.fetchone()
            assert row["cnt"] == 2


class TestIndexAll:
    """Test bulk indexing."""

    async def test_index_all_incremental(self, initialized_db):
        """Incremental indexing skips already-indexed sessions."""
        await _seed_session("test-010", [("user", "First session"), ("text", "Reply")])
        await _seed_session("test-011", [("user", "Second session"), ("text", "Reply")])

        result1 = await index_all_sessions(force=False)
        assert result1["indexed"] >= 2

        result2 = await index_all_sessions(force=False)
        assert result2["skipped"] >= 2
        assert result2["indexed"] == 0

    async def test_index_all_force(self, initialized_db):
        """Force rebuild re-indexes everything."""
        await _seed_session("test-020", [("user", "Force test"), ("text", "Reply")])
        await index_all_sessions(force=False)

        result = await index_all_sessions(force=True)
        assert result["indexed"] >= 1
        assert result["skipped"] == 0


class TestSearch:
    """Test FTS5 keyword search."""

    async def test_search_finds_keyword(self, initialized_db):
        """Search finds messages containing the keyword."""
        await _seed_session("test-030", [
            ("user", "Tell me about quantum computing"),
            ("text", "Quantum computing uses qubits instead of classical bits."),
        ])
        await index_session("test-030")

        results = await search_history("quantum")
        assert len(results) > 0
        assert any("test-030" == r["session_id"] for r in results)

    async def test_search_empty_query(self, initialized_db):
        """Empty query returns no results."""
        results = await search_history("")
        assert results == []

    async def test_search_no_match(self, initialized_db):
        """Search with no matches returns empty list."""
        results = await search_history("xyznonexistentkeyword123")
        assert results == []

    async def test_search_with_session_filter(self, initialized_db):
        """Search within a specific session."""
        await _seed_session("test-031", [("user", "Alpha topic"), ("text", "Alpha reply")])
        await _seed_session("test-032", [("user", "Alpha other"), ("text", "Alpha other reply")])
        await index_session("test-031")
        await index_session("test-032")

        results = await search_history("Alpha", session_filter="test-031")
        assert all(r["session_id"] == "test-031" for r in results)


class TestRetrieve:
    """Test conversation retrieval."""

    async def test_retrieve_clean(self, initialized_db):
        """Retrieve returns only user and text messages by default."""
        await _seed_session("test-040", [
            ("user", "Hello"),
            ("text", "Hi!"),
            ("tool_use", "search tool"),
            ("tool_result", "search result"),
            ("thinking", "I should respond"),
            ("user", "Goodbye"),
            ("text", "Bye!"),
        ])

        result = await retrieve_conversation("test-040")
        assert result["session_id"] == "test-040"
        assert result["clean_messages_returned"] == 4  # 2 user + 2 text
        types = {m["type"] for m in result["messages"]}
        assert types == {"user", "text"}

    async def test_retrieve_with_tool_results(self, initialized_db):
        """Retrieve with include_tool_results includes tool messages."""
        await _seed_session("test-041", [
            ("user", "Hello"),
            ("tool_use", "search tool"),
            ("tool_result", "search result"),
            ("text", "Found it!"),
        ])

        result = await retrieve_conversation("test-041", include_tool_results=True)
        types = {m["type"] for m in result["messages"]}
        assert "tool_use" in types
        assert "tool_result" in types

    async def test_retrieve_with_thinking(self, initialized_db):
        """Retrieve with include_thinking includes thinking blocks."""
        await _seed_session("test-042", [
            ("user", "Hello"),
            ("thinking", "Let me think about this"),
            ("text", "Here is my answer"),
        ])

        result = await retrieve_conversation("test-042", include_thinking=True)
        types = {m["type"] for m in result["messages"]}
        assert "thinking" in types

    async def test_retrieve_with_max_chars(self, initialized_db):
        """Retrieve with max_chars truncates output."""
        long_text = "A" * 5000
        await _seed_session("test-043", [
            ("user", long_text),
            ("text", long_text),
        ])

        result = await retrieve_conversation("test-043", max_chars=1000)
        assert result["total_clean_chars"] <= 1100  # some slack for truncation marker

    async def test_retrieve_nonexistent(self, initialized_db):
        """Retrieve nonexistent session returns error."""
        result = await retrieve_conversation("nonexistent-session")
        assert "error" in result


class TestListIndexed:
    """Test listing indexed sessions."""

    async def test_list_returns_sessions(self, initialized_db):
        """list_indexed_sessions returns previously indexed sessions."""
        await _seed_session("test-050", [("user", "List test"), ("text", "Reply")])
        await index_session("test-050")

        sessions = await list_indexed_sessions()
        assert any(s["session_id"] == "test-050" for s in sessions)

    async def test_list_includes_token_estimate(self, initialized_db):
        """Listed sessions include estimated_tokens field."""
        await _seed_session("test-051", [("user", "Token estimate test"), ("text", "Reply")])
        await index_session("test-051")

        sessions = await list_indexed_sessions()
        matching = [s for s in sessions if s["session_id"] == "test-051"]
        assert len(matching) == 1
        assert "estimated_tokens" in matching[0]
        assert matching[0]["estimated_tokens"] > 0
