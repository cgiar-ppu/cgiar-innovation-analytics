"""
Tests for update_workflow_status() in synapsis/services/workflow_persistence.py.

The function builds a dynamic UPDATE statement from **kwargs and appends
`updated_at` and `workflow_id` to the parameter list.  The critical
invariant is that SQL parameters are in the correct positional order:

    SET clause values  →  updated_at  →  workflow_id (WHERE clause)

A bug where kwargs.values() and the WHERE params were assembled in the
wrong order would cause SQLite to receive mismatched values, silently
corrupting workflow rows.

These tests import update_workflow_status directly and exercise it
against an isolated temp database (via the initialized_db fixture).
"""

import time
import uuid
import pytest
import aiosqlite
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_workflow(db_path: Path, wf_id: str, **kwargs) -> None:
    """Insert a workflow row for test setup."""
    now = time.time()
    defaults = dict(
        name="Test Workflow",
        description="desc",
        status="draft",
        progress=0,
        agent_sequence="[]",
        nodes="[]",
        edges="[]",
        step_configs="[]",
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO workflows
               (id, name, description, status, progress, agent_sequence,
                nodes, edges, step_configs, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                wf_id,
                defaults["name"],
                defaults["description"],
                defaults["status"],
                defaults["progress"],
                defaults["agent_sequence"],
                defaults["nodes"],
                defaults["edges"],
                defaults["step_configs"],
                defaults["created_at"],
                defaults["updated_at"],
            ),
        )
        await db.commit()


async def _get_workflow(db_path: Path, wf_id: str) -> dict | None:
    """Fetch a single workflow row as a dict."""
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM workflows WHERE id = ?", (wf_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_workflow_status_single_kwarg(initialized_db: Path):
    """Update with a single kwarg changes only that field."""
    wf_id = str(uuid.uuid4())
    await _create_workflow(initialized_db, wf_id, status="draft", progress=0)

    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        await update_workflow_status(wf_id, status="running")

    row = await _get_workflow(initialized_db, wf_id)
    assert row is not None
    assert row["status"] == "running"
    assert row["progress"] == 0   # unchanged


@pytest.mark.asyncio
async def test_update_workflow_status_multiple_kwargs(initialized_db: Path):
    """Update with multiple kwargs changes all specified fields."""
    wf_id = str(uuid.uuid4())
    await _create_workflow(initialized_db, wf_id, status="running", progress=50)

    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        await update_workflow_status(wf_id, status="completed", progress=100)

    row = await _get_workflow(initialized_db, wf_id)
    assert row is not None
    assert row["status"] == "completed"
    assert row["progress"] == 100


@pytest.mark.asyncio
async def test_update_workflow_status_updates_updated_at(initialized_db: Path):
    """updated_at must be set to a recent timestamp by update_workflow_status."""
    wf_id = str(uuid.uuid4())
    old_time = time.time() - 3600   # 1 hour ago
    await _create_workflow(initialized_db, wf_id, status="draft", updated_at=old_time)

    before_call = time.time()
    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        await update_workflow_status(wf_id, status="running")

    row = await _get_workflow(initialized_db, wf_id)
    assert row is not None
    # updated_at must be >= the timestamp captured just before calling the function
    assert row["updated_at"] >= before_call, (
        f"updated_at ({row['updated_at']}) was not refreshed (expected >= {before_call})"
    )


@pytest.mark.asyncio
async def test_update_workflow_status_noop_when_no_kwargs(initialized_db: Path):
    """Calling update_workflow_status with no kwargs is a safe no-op."""
    wf_id = str(uuid.uuid4())
    await _create_workflow(initialized_db, wf_id, status="draft")

    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        # Must not raise
        await update_workflow_status(wf_id)

    row = await _get_workflow(initialized_db, wf_id)
    assert row["status"] == "draft"   # unchanged


@pytest.mark.asyncio
async def test_update_workflow_status_parameter_order(initialized_db: Path):
    """Critical: SQL parameters must be in the correct order (values → updated_at → id).

    This test explicitly verifies that the status and progress values end up
    in the correct columns and are not swapped with updated_at or workflow_id
    due to a parameter ordering bug.
    """
    wf_id = str(uuid.uuid4())
    await _create_workflow(initialized_db, wf_id, status="draft", progress=0)

    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        # Pass both a string and an integer to expose any type-mixing bug
        await update_workflow_status(wf_id, status="failed", progress=75)

    row = await _get_workflow(initialized_db, wf_id)
    assert row is not None

    # If parameters were in wrong order, status and progress would be
    # mixed up with updated_at (a float) or the workflow_id (a string UUID).
    assert row["status"] == "failed", (
        f"status={row['status']!r} — possible parameter order bug"
    )
    assert row["progress"] == 75, (
        f"progress={row['progress']} — possible parameter order bug"
    )
    # updated_at should be a reasonable Unix timestamp (> year 2020)
    assert row["updated_at"] > 1_580_000_000, (
        f"updated_at={row['updated_at']} looks wrong — possible parameter order bug"
    )


@pytest.mark.asyncio
async def test_update_workflow_status_does_not_affect_other_workflows(initialized_db: Path):
    """Updating one workflow must not modify unrelated workflow rows."""
    wf_id_a = str(uuid.uuid4())
    wf_id_b = str(uuid.uuid4())
    await _create_workflow(initialized_db, wf_id_a, status="draft")
    await _create_workflow(initialized_db, wf_id_b, status="draft")

    with patch("synapsis.database.DB_PATH", initialized_db):
        from synapsis.services.workflow_persistence import update_workflow_status
        await update_workflow_status(wf_id_a, status="running")

    row_a = await _get_workflow(initialized_db, wf_id_a)
    row_b = await _get_workflow(initialized_db, wf_id_b)

    assert row_a["status"] == "running"
    assert row_b["status"] == "draft", "Unrelated workflow was affected"
