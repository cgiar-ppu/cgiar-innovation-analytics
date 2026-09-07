"""Tests for synapsis.prms_snapshot — the single source of truth for the PRMS snapshot."""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from synapsis import prms_snapshot as ps


def _make_db(path, *, max_updated="2026-09-04 02:59:36.826833", rows=3, open_phase=True):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INTEGER, last_updated_date TEXT);
        CREATE TABLE version (id INTEGER PRIMARY KEY, phase_name TEXT, status INTEGER, is_active INTEGER);
        INSERT INTO version VALUES (6, 'Reporting 2025', 0, 1);
        """
    )
    if open_phase:
        conn.execute("INSERT INTO version VALUES (8, 'Reporting 2026', 1, 1)")
    for i in range(rows):
        conn.execute(
            "INSERT INTO result VALUES (?, ?, ?)",
            (i + 1, 1000 + i, "2026-01-01 00:00:00" if i else max_updated),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A fake PRMSDB root with a dated folder, a `current` symlink and LATEST.json."""
    folder = tmp_path / "fresh_20260907"
    folder.mkdir()
    db = folder / "prdb_20260907.sqlite"
    _make_db(str(db))
    current = tmp_path / "current"
    current.symlink_to(db)
    (tmp_path / "LATEST.json").write_text(
        json.dumps(
            {
                "sqlite": str(db),
                "snapshot_date": "20260907",
                "result_count": 32194,
                "table_count": 199,
                "max_last_updated_date": "2026-09-04 02:59:36.826833",
            }
        )
    )
    monkeypatch.setenv("PRMS_DB_ROOT", str(tmp_path))
    monkeypatch.delenv("PRMS_DB_PATH", raising=False)
    ps._cache.clear()
    return tmp_path


def test_default_path_is_current_symlink(root):
    assert ps.resolve_db_path() == str(root / "current")


def test_env_override_wins(root, monkeypatch):
    monkeypatch.setenv("PRMS_DB_PATH", "/tmp/somewhere.sqlite")
    assert ps.resolve_db_path() == "/tmp/somewhere.sqlite"


def test_latest_json_is_used_when_it_describes_the_same_file(root):
    info = ps.get_snapshot_info()
    assert info.available
    assert info.source == "latest.json"
    assert info.extracted_on == "2026-09-07"
    assert info.data_as_of == "2026-09-04"
    assert info.result_count == 32194
    assert info.open_phases == ("8 Reporting 2026",)
    assert info.label == "PRMS snapshot 2026-09-07 (data as of 2026-09-04)"
    assert info.citation == "PRMS Database (snapshot 2026-09-07, data as of 2026-09-04)"


def test_latest_json_ignored_for_a_different_file(root, tmp_path):
    other_dir = tmp_path / "fresh_13June2026"
    other_dir.mkdir()
    other = other_dir / "prdb_fresh.sqlite"
    _make_db(str(other), max_updated="2026-06-12 16:57:11.748908", rows=5, open_phase=False)
    info = ps.get_snapshot_info(str(other))
    assert info.source == "sqlite"
    assert info.extracted_on == "2026-06-13"  # parsed from fresh_13June2026
    assert info.data_as_of == "2026-06-12"
    assert info.result_count == 5
    assert info.open_phases == ()


def test_sqlite_fallback_infers_date_from_folder_name(root, tmp_path):
    (root / "LATEST.json").unlink()
    ps._cache.clear()
    info = ps.get_snapshot_info()
    assert info.source == "sqlite"
    assert info.extracted_on == "2026-09-07"
    assert info.data_as_of == "2026-09-04"
    assert info.result_count == 3


def test_missing_file_is_unavailable_not_an_error(root):
    info = ps.get_snapshot_info(str(root / "nope.sqlite"))
    assert not info.available
    assert info.label == "PRMS snapshot unavailable"
    assert info.citation == "PRMS Database (snapshot unavailable)"


def test_cache_follows_symlink_retarget(root):
    first = ps.get_snapshot_info()
    assert first.result_count == 32194
    # Daily refresh publishes a new folder and retargets `current`.
    folder = root / "fresh_20260908"
    folder.mkdir()
    db = folder / "prdb_20260908.sqlite"
    _make_db(str(db), max_updated="2026-09-08 01:00:00", rows=7)
    os.remove(root / "current")
    (root / "current").symlink_to(db)
    (root / "LATEST.json").unlink()  # simulate stale pointer → sqlite fallback
    second = ps.get_snapshot_info()
    assert second.extracted_on == "2026-09-08"
    assert second.data_as_of == "2026-09-08"
    assert second.result_count == 7


def test_to_dict_is_json_serialisable(root):
    payload = json.dumps(ps.get_snapshot_info().to_dict())
    assert '"label"' in payload and '"open_phases"' in payload
