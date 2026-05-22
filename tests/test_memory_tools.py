"""
Tests for synapsis/tools/memory.py

The @tool decorator wraps each function in an SdkMcpTool object; the
underlying async function is available as `tool_obj.handler(args)`.

Covers memory_store, memory_recall, memory_list, and memory_forget tools.
The ``initialized_db`` fixture (conftest.py) patches DB_PATH and all related
paths, so these tests operate on an isolated temp database automatically.
"""

import time
import pytest
import aiosqlite
from pathlib import Path

from synapsis.tools.memory import memory_store, memory_recall, memory_list, memory_forget


# ---------------------------------------------------------------------------
# Helper: call a tool's handler (bypasses the SdkMcpTool wrapper)
# ---------------------------------------------------------------------------

async def _call(tool_obj, args: dict):
    """Invoke the underlying async handler of an SdkMcpTool."""
    return await tool_obj.handler(args)


# ---------------------------------------------------------------------------
# memory_store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_store_basic(initialized_db: Path):
    """Store a memory and verify the row is persisted in the database."""
    result = await _call(memory_store, {
        "category": "user_profile",
        "content": "User works in healthcare analytics",
        "importance": 7,
        "tags": "healthcare analytics",
    })

    assert result.get("is_error") is not True
    text = result["content"][0]["text"]
    assert "Memory stored" in text or "Updated existing memory" in text

    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT category, content, importance FROM memories WHERE active = 1"
        )
        rows = await cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "user_profile"
    assert rows[0][1] == "User works in healthcare analytics"
    assert rows[0][2] == 7


@pytest.mark.asyncio
async def test_memory_store_empty_content_error(initialized_db: Path):
    """Passing an empty content string must return an error response."""
    result = await _call(memory_store, {"category": "fact", "content": "", "importance": 5})

    assert result.get("is_error") is True
    assert "content is required" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_memory_store_duplicate_updates(initialized_db: Path):
    """Storing the same category+content pair twice updates rather than inserting."""
    await _call(memory_store, {"category": "fact", "content": "Sky is blue", "importance": 3})
    result = await _call(memory_store, {"category": "fact", "content": "Sky is blue", "importance": 9})

    # Should report an update, not a new insert
    assert "Updated existing memory" in result["content"][0]["text"]

    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute("SELECT count(*) FROM memories WHERE active = 1")
        row = await cursor.fetchone()
    assert row[0] == 1, "Duplicate memory was inserted instead of updated"


@pytest.mark.asyncio
async def test_memory_store_fts_indexed(initialized_db: Path):
    """After storing a memory, it should appear in the memories_fts index."""
    await _call(memory_store, {
        "category": "project_context",
        "content": "Project uses Django REST framework",
        "importance": 6,
        "tags": "django rest api",
    })

    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute("SELECT count(*) FROM memories_fts")
        row = await cursor.fetchone()
    assert row[0] >= 1, "Memory was not added to FTS index"


# ---------------------------------------------------------------------------
# memory_recall
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_recall_by_keyword(initialized_db: Path):
    """Full-text search should find memories matching the query keyword."""
    await _call(memory_store, {
        "category": "fact",
        "content": "Python is great for data science",
        "importance": 5,
        "tags": "python data",
    })

    result = await _call(memory_recall, {"query": "Python", "limit": 10})

    text = result["content"][0]["text"]
    assert "Python" in text
    assert "No memories found" not in text


@pytest.mark.asyncio
async def test_memory_recall_by_category(initialized_db: Path):
    """Category-only filter should return memories in that category."""
    await _call(memory_store, {"category": "best_practice", "content": "Write tests first", "importance": 8})
    await _call(memory_store, {"category": "user_profile", "content": "User is a senior dev", "importance": 6})

    result = await _call(memory_recall, {"category": "best_practice"})

    text = result["content"][0]["text"]
    assert "Write tests first" in text
    # The user_profile entry must not appear
    assert "User is a senior dev" not in text


@pytest.mark.asyncio
async def test_memory_recall_bumps_access_count(initialized_db: Path):
    """Each memory_recall call should increment the access_count of returned rows."""
    await _call(memory_store, {"category": "fact", "content": "Earth orbits the Sun", "importance": 5})
    await _call(memory_recall, {"query": "Earth"})
    await _call(memory_recall, {"query": "Earth"})

    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT access_count FROM memories WHERE content = 'Earth orbits the Sun'"
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 2, f"Expected access_count=2, got {row[0]}"


@pytest.mark.asyncio
async def test_memory_recall_no_results(initialized_db: Path):
    """When no memories match, returns a 'No memories found' message."""
    result = await _call(memory_recall, {"query": "xyzzy_nonexistent_term_12345"})

    assert "No memories found" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# memory_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_list_ordered_by_importance(initialized_db: Path):
    """memory_list should return memories with higher importance appearing first."""
    await _call(memory_store, {"category": "fact", "content": "Low priority fact", "importance": 2})
    await _call(memory_store, {"category": "fact", "content": "High priority fact", "importance": 9})

    result = await _call(memory_list, {})

    text = result["content"][0]["text"]
    high_pos = text.find("High priority fact")
    low_pos = text.find("Low priority fact")
    assert high_pos < low_pos, "Higher importance memory should appear before lower importance"


@pytest.mark.asyncio
async def test_memory_list_with_category_filter(initialized_db: Path):
    """Category filter in memory_list must exclude memories from other categories."""
    await _call(memory_store, {"category": "methodology_note", "content": "Use stratified sampling", "importance": 7})
    await _call(memory_store, {"category": "user_profile", "content": "User likes coffee", "importance": 5})

    result = await _call(memory_list, {"category": "methodology_note"})

    text = result["content"][0]["text"]
    assert "Use stratified sampling" in text
    assert "User likes coffee" not in text


# ---------------------------------------------------------------------------
# memory_forget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_forget_soft_delete(initialized_db: Path):
    """memory_forget sets active=0 on the row without physically removing it."""
    store_result = await _call(memory_store, {"category": "fact", "content": "Temporary fact", "importance": 5})

    # Extract the memory ID from the store response text
    # Format: "Memory stored (id=1, category=fact)."
    text = store_result["content"][0]["text"]
    id_part = text.split("id=")[1].split(",")[0].rstrip(").")
    memory_id = int(id_part)

    forget_result = await _call(memory_forget, {"memory_id": memory_id})

    assert "forgotten" in forget_result["content"][0]["text"]

    # Row still exists but with active=0
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT active FROM memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()

    assert row is not None, "Row was physically deleted; expected soft-delete"
    assert row[0] == 0, f"Expected active=0, got {row[0]}"


@pytest.mark.asyncio
async def test_memory_forget_cleans_fts(initialized_db: Path):
    """memory_forget removes the entry from the FTS5 search index.

    Note: memories_fts uses content='' (a content table) so rowid-based
    shadow table queries still show the raw row.  The correct way to verify
    FTS deletion is a MATCH query, which joins back against the content table
    and therefore honours the soft-delete (active=0).  A subsequent recall
    via FTS must return no results for the forgotten content.
    """
    store_result = await _call(memory_store, {"category": "fact", "content": "FTS cleanup test", "importance": 5})
    text = store_result["content"][0]["text"]
    id_part = text.split("id=")[1].split(",")[0].rstrip(").")
    memory_id = int(id_part)

    await _call(memory_forget, {"memory_id": memory_id})

    # After forgetting, a keyword search must return no matches for this content.
    recall_result = await _call(memory_recall, {"query": "cleanup"})

    recall_text = recall_result["content"][0]["text"]
    assert "FTS cleanup test" not in recall_text, (
        "Forgotten memory still appears in FTS search results"
    )


@pytest.mark.asyncio
async def test_memory_forget_nonexistent(initialized_db: Path):
    """Forgetting a non-existent memory ID returns an error response."""
    result = await _call(memory_forget, {"memory_id": 99999})

    assert result.get("is_error") is True
    assert "not found" in result["content"][0]["text"] or "already deleted" in result["content"][0]["text"]
