"""
Tests for synapsis.db_init — PRMS result-table index initialization.

These tests use a small disposable temp SQLite DB (not the real 400MB PRMS
artifact) so they run fast and have no external dependencies.
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.db_init import ensure_result_indexes, RESULT_TABLE_INDEXES


def _make_result_db(path: str) -> None:
    """Create a minimal `result` table mirroring the PRMS columns we index."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE result (
            id INTEGER PRIMARY KEY,
            result_code INTEGER,
            result_type_id INTEGER,
            reported_year_id INTEGER,
            is_active INTEGER,
            is_discontinued INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO result (id, result_code, result_type_id, reported_year_id, "
        "is_active, is_discontinued) VALUES (?, ?, ?, ?, ?, ?)",
        [(i, 1000 + i, (i % 3) and 7, 2024, 1, 0) for i in range(1, 101)],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    _make_result_db(path)
    yield path
    os.remove(path)


def _index_names(path: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='result'"
            ).fetchall()
        }
    finally:
        conn.close()


def test_creates_all_five_indexes(temp_db):
    before = _index_names(temp_db)
    expected = {idx["name"] for idx in RESULT_TABLE_INDEXES}
    assert not (expected & before)  # none present yet

    ensure_result_indexes(temp_db)

    after = _index_names(temp_db)
    assert expected.issubset(after)
    assert len(expected) == 5


def test_idempotent(temp_db):
    ensure_result_indexes(temp_db)
    first = _index_names(temp_db)
    # Second call must be a no-op and must not raise.
    ensure_result_indexes(temp_db)
    second = _index_names(temp_db)
    assert first == second


def test_missing_db_does_not_raise(tmp_path):
    # A non-existent path should be handled gracefully (no exception bubbles up).
    bogus = str(tmp_path / "does_not_exist_dir" / "nope.sqlite")
    # sqlite3.connect on a path in a missing directory raises OperationalError;
    # ensure_result_indexes must swallow it.
    ensure_result_indexes(bogus)


def test_missing_result_table_does_not_raise(tmp_path):
    path = str(tmp_path / "empty.sqlite")
    sqlite3.connect(path).close()  # valid DB, but no `result` table
    # Index creation will fail (no such table) but must not raise.
    ensure_result_indexes(path)
