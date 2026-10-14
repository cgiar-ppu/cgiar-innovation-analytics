"""Innovation Use levels / use numbers (Marc Schut, 13 Oct 2026).

The 2026-09-13 snapshot silently lacked ``results_innovations_use`` and
``result_actors``; the agent then said PRMS has no 0-9 use levels, joined
``results_innovations_use_measures`` to the wrong key, and could not read
use numbers in descriptions because ``prms_query`` cut every cell at 80
characters. These tests pin the four fixes:

1. schema self-check (``synapsis.prms_schema_check``) + its surfaces
   (prompt warning, ``prms_query`` error text, admin ``/api/health``);
2. ``prms_query`` long-text display (shared budget instead of a flat 80);
3. the references document the real join paths (Recipe 11);
4. the recipe SQL returns use levels/numbers on a synthetic snapshot and, when
   a real snapshot with the tables is configured, on real data.
"""

import asyncio
import os
import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis import prms_schema_check as sc  # noqa: E402
import importlib  # noqa: E402

# ``synapsis.tools`` re-exports the tool object under the module's name.
pq = importlib.import_module("synapsis.tools.prms_query")

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "references"


# ---------------------------------------------------------------------------
# Synthetic snapshots
# ---------------------------------------------------------------------------

def _make_db(path: Path, skip: set[str] = frozenset()) -> Path:
    """A snapshot holding every expected table (minus *skip*) with the use-data
    columns the recipe needs, and a few Innovation Use rows."""
    conn = sqlite3.connect(path)
    for t in sc.EXPECTED_TABLES:
        if t in skip:
            continue
        if t == "result":
            conn.execute(
                "CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INT, title TEXT, "
                "description TEXT, result_type_id INT, is_active INT, status_id INT, "
                "source TEXT, reported_year_id INT, version_id INT, last_updated_date TEXT)"
            )
        elif t == "results_innovations_use":
            conn.execute(
                "CREATE TABLE results_innovations_use (result_innovation_use_id INTEGER PRIMARY KEY, "
                "results_id INT UNIQUE, innovation_use_level_id INT, new_users_added INT, is_active INT)"
            )
        elif t == "clarisa_innovation_use_levels":
            conn.execute("CREATE TABLE clarisa_innovation_use_levels (id INT, name TEXT, level INT)")
        elif t == "result_actors":
            conn.execute(
                "CREATE TABLE result_actors (result_actors_id INTEGER PRIMARY KEY, result_id INT, "
                "actor_type_id INT, how_many INT, women INT, men INT, other_actor_type TEXT, "
                "section_id INT, is_active INT)"
            )
        elif t == "actor_type":
            conn.execute("CREATE TABLE actor_type (actor_type_id INT, name TEXT)")
        elif t == "results_innovations_use_measures":
            conn.execute(
                "CREATE TABLE results_innovations_use_measures (result_innovations_use_measure_id "
                "INTEGER PRIMARY KEY, result_innovation_use_id INT, quantity REAL, "
                "unit_of_measure TEXT, is_active INT)"
            )
        else:
            conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY)")
    if "result" not in skip:
        # Two QAed 2025 Innovation Use results + an unrelated result whose
        # result.id equals a result_innovation_use_id.
        conn.executemany(
            "INSERT INTO result VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (100, 24600, "CS-MAP adopted", "d", 2, 1, 2, "Result", 2025, 6, "2026-09-12"),
                (101, 22751, "Direct seeding Morocco", "d", 2, 1, 2, "Result", 2025, 6, "2026-09-12"),
                (7, 999, "Unrelated knowledge product", "d", 6, 1, 2, "Result", 2025, 6, "2026-09-12"),
            ],
        )
    if "results_innovations_use" not in skip:
        conn.executemany(
            "INSERT INTO results_innovations_use VALUES (?,?,?,?,?)",
            [(7, 100, 9, 1200, 1), (8, 101, 10, None, 1)],
        )
    if "clarisa_innovation_use_levels" not in skip:
        conn.executemany(
            "INSERT INTO clarisa_innovation_use_levels VALUES (?,?,?)",
            [(i + 1, f"name{i}", i) for i in range(10)],
        )
    if "result_actors" not in skip:
        conn.executemany(
            "INSERT INTO result_actors VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (1, 100, 1, 171561, None, None, None, 1, 1),
                (2, 100, 1, 500000, None, None, None, 2, 1),  # 2030 target: never added
            ],
        )
    if "actor_type" not in skip:
        conn.execute("INSERT INTO actor_type VALUES (1, 'Farmers')")
    if "results_innovations_use_measures" not in skip:
        conn.execute("INSERT INTO results_innovations_use_measures VALUES (1, 8, 160000, 'Area (ha)', 1)")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def full_db(tmp_path):
    return _make_db(tmp_path / "full.sqlite")


@pytest.fixture
def degraded_db(tmp_path):
    return _make_db(tmp_path / "degraded.sqlite", skip={"results_innovations_use", "result_actors"})


def _query(sql: str, db: Path) -> dict:
    with patch.object(pq, "PRMS_DB_PATH", str(db)):
        return asyncio.run(pq.prms_query.handler({"sql": sql, "question": "t"}))


def _text(result: dict) -> str:
    return result["content"][0]["text"]


# ---------------------------------------------------------------------------
# 1. Schema self-check
# ---------------------------------------------------------------------------

class TestSchemaCheck:

    def test_marcs_tables_are_expected(self):
        for t in ("results_innovations_use", "result_actors", "results_innovations_use_measures",
                  "clarisa_innovation_use_levels", "result_innov_section", "results_by_institution_type"):
            assert sc.is_expected_table(t), t
        # The auth table the converter also dropped must NOT be required.
        assert not sc.is_expected_table("otp_challenges")

    def test_complete_snapshot_is_ok(self, full_db):
        r = sc.check_schema(str(full_db), refresh=True)
        assert r["status"] == "ok" and r["missing"] == []
        assert r["expected"] == len(sc.EXPECTED_TABLES)
        assert sc.prompt_warning(str(full_db)) == ""

    def test_missing_tables_degrade_and_are_named(self, degraded_db):
        r = sc.check_schema(str(degraded_db), refresh=True)
        assert r["status"] == "degraded"
        assert {m["table"] for m in r["missing"]} == {"results_innovations_use", "result_actors"}
        assert all(m["carries"] for m in r["missing"])
        assert sc.missing_expected_tables(str(degraded_db)) == ["results_innovations_use", "result_actors"]

    def test_unavailable_and_corrupt_files_never_raise(self, tmp_path):
        assert sc.check_schema(str(tmp_path / "nope.sqlite"))["status"] == "unavailable"
        bad = tmp_path / "bad.sqlite"
        bad.write_bytes(b"this is not a database" * 100)
        assert sc.check_schema(str(bad), refresh=True)["status"] == "unavailable"
        assert sc.prompt_warning(str(bad)) == ""

    def test_prompt_warning_names_tables_and_forbids_speculation(self, degraded_db):
        w = sc.prompt_warning(str(degraded_db))
        assert "DATA HEALTH WARNING" in w
        assert "`results_innovations_use`" in w and "`result_actors`" in w
        assert "CLARISA API" in w and "do NOT guess" in w

    def test_system_prompt_carries_the_warning_only_when_degraded(self, degraded_db, full_db):
        from synapsis import system_prompt as sp
        with patch.object(sp, "prompt_warning", lambda: sc.prompt_warning(str(degraded_db))):
            assert "DATA HEALTH WARNING" in sp.build_system_prompt()
        with patch.object(sp, "prompt_warning", lambda: sc.prompt_warning(str(full_db))):
            assert "DATA HEALTH WARNING" not in sp.build_system_prompt()


class TestPrmsQueryMissingTable:

    def test_expected_missing_table_is_reported_as_pipeline_issue(self, degraded_db):
        r = _query("SELECT * FROM results_innovations_use", degraded_db)
        assert r.get("is_error") is True
        t = _text(r)
        assert "missing from the loaded snapshot" in t and "data-pipeline" in t
        assert "might be named differently" not in t

    def test_unknown_table_keeps_the_naming_hint(self, degraded_db):
        t = _text(_query("SELECT * FROM initiatives", degraded_db))
        assert "might be named differently" in t
        assert "missing from the loaded snapshot" not in t


@pytest.mark.asyncio
async def test_admin_health_reports_prms_data_and_anonymous_does_not():
    from httpx import ASGITransport, AsyncClient
    from synapsis.auth.tokens import create_access_token
    from synapsis.server import app

    with patch("synapsis.config.AUTH_DISABLED", False), patch("synapsis.auth.middleware.AUTH_DISABLED", False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            anon = (await http.get("/api/health")).json()
            assert "prms_data" not in anon and anon["status"] == "ok"
            tok = create_access_token("admin@cgiar.org", "admin", "admin")
            admin = (await http.get("/api/health", headers={"Authorization": f"Bearer {tok}"})).json()
            assert admin["prms_data"]["status"] in {"ok", "degraded", "unavailable"}
            assert isinstance(admin["prms_data"]["missing"], list)


# ---------------------------------------------------------------------------
# 2. Long text display
# ---------------------------------------------------------------------------

def _fmt(rows, columns):
    return pq._format_results_text(rows, columns, None, "SELECT 1", ["result"])


class TestLongText:

    def test_eighteen_descriptions_come_back_in_full(self):
        # 13 Oct: 18 candidates, descriptions 376-2,396 chars, all cut to 80.
        desc = "x" * 2396
        rows = [{"result_code": i, "title": "t", "description": desc + str(i)} for i in range(18)]
        out = _fmt(rows, ["result_code", "title", "description"])
        assert all((desc + str(i)) in out for i in range(18))
        assert "shortened" not in out

    def test_substr_chunks_are_not_cut_again(self):
        # 30 Sep / 13 Oct workaround: substr(...,1,200) AS c1 … c8 → each chunk cut to 80.
        cols = ["dev_code", "result_code", "year"] + [f"c{i}" for i in range(1, 9)]
        rows = [{**{"dev_code": 1, "result_code": i, "year": 2025},
                 **{f"c{k}": ("y" * 199) + str(k) for k in range(1, 9)}} for i in range(6)]
        out = _fmt(rows, cols)
        assert ("y" * 199 + "8") in out and "shortened" not in out

    def test_large_result_sets_keep_the_80_char_floor_and_say_so(self):
        rows = [{"result_code": i, "description": "z" * 500} for i in range(5000)]
        out = _fmt(rows, ["result_code", "description"])
        line = out.splitlines()[5]
        assert line.endswith("...") and len(line.split(" | ")[1]) == 80
        assert "NOTE: 5000 long text value(s) were shortened" in out
        assert "display limit, not the stored text" in out

    def test_extra_output_is_bounded_by_the_budget(self):
        rows = [{"a": "q" * 6000, "b": "r" * 6000} for _ in range(40)]
        out = _fmt(rows, ["a", "b"])
        assert len(out) < pq.LONG_TEXT_BUDGET + 10_000

    def test_titles_keep_at_least_250(self):
        rows = [{"title": "T" * 400, "description": "D" * 400} for _ in range(2000)]
        out = _fmt(rows, ["title", "description"])
        title_cell = out.splitlines()[5].split(" | ")[0]
        assert len(title_cell) == 250

    def test_one_long_value_capped_at_max_cell_limit(self):
        out = _fmt([{"description": "w" * 50_000}], ["description"])
        cell = out.splitlines()[5]
        assert len(cell) == pq.MAX_CELL_LIMIT and cell.endswith("...")

    def test_wide_queries_say_rows_were_not_printed(self):
        cols = [f"k{i}" for i in range(14)]
        rows = [{c: 1 for c in cols} for _ in range(30)]
        out = _fmt(rows, cols)
        assert out.count("--- Row ") == pq.KV_MAX_ROWS
        assert "only the first 20 of 30 rows are printed" in out

    def test_tool_description_documents_the_limits(self):
        desc = pq.prms_query.description
        assert "Long text" in desc and "48,000" in desc and "missing from the loaded snapshot" in desc

    def test_water_level(self):
        assert pq._water_level([10, 10], 100) == pq._UNLIMITED
        assert pq._water_level([10, 1000, 1000], 210) == 100
        assert pq._water_level([], 10) == pq._UNLIMITED


# ---------------------------------------------------------------------------
# 3. References document the real join paths
# ---------------------------------------------------------------------------

class TestReferences:

    def test_cookbook_has_recipe_11_with_correct_joins(self):
        text = (REFERENCES / "prms_query_cookbook.md").read_text()
        assert "## Recipe 11: Innovation Use detail" in text
        assert "m.result_innovation_use_id = riu.result_innovation_use_id" in text
        assert "iul.id = riu.innovation_use_level_id" in text
        assert "COALESCE(ra.section_id, 1) = 1" in text
        assert "DO NOT join `results_innovations_use_measures` to `result.id`" in text

    def test_schema_reference_documents_measures_and_sections(self):
        text = (REFERENCES / "prms_schema_reference.md").read_text()
        for needle in ("### `results_innovations_use_measures`", "### `result_innov_section`",
                       "### `results_by_institution_type`", "`new_users_added`", "id = level + 1"):
            assert needle in text, needle

    def test_data_guide_says_missing_table_is_a_loading_problem(self):
        text = (REFERENCES / "prms_data_guide.md").read_text()
        assert "Missing table = data-loading problem" in text
        assert "result_innovation_use_id → results_innovations_use.result_innovation_use_id" in text

    def test_persona_no_longer_calls_the_lookup_id_the_level(self):
        text = (ROOT / "synapsis" / "agents" / "definitions.py").read_text()
        assert "`innovation_use_level_id` (0-9)" not in text
        assert "results_innovations_use_measures" in text

    def test_prompt_rules_on_use_data_and_speculation(self):
        from synapsis.system_prompt import build_system_prompt
        p = build_system_prompt()
        assert "Innovation Use level (0-9) and use numbers ARE stored in PRMS" in p
        assert "No invented explanations or requirements" in p
        assert "This rule is about ToC names ONLY" in p


# ---------------------------------------------------------------------------
# 4. The recipe SQL works
# ---------------------------------------------------------------------------

def _recipe_11_sql() -> str:
    text = (REFERENCES / "prms_query_cookbook.md").read_text()
    section = text.split("## Recipe 11:", 1)[1]
    return re.search(r"```sql\n(.*?)```", section, re.S).group(1)


def test_recipe_11_on_synthetic_snapshot(full_db):
    conn = sqlite3.connect(full_db)
    conn.row_factory = sqlite3.Row
    rows = {r["result_code"]: dict(r) for r in conn.execute(_recipe_11_sql())}
    conn.close()
    assert set(rows) == {24600, 22751}
    assert rows[24600]["use_level"] == 8 and rows[22751]["use_level"] == 9  # id - 1
    assert rows[24600]["users_current"] == 171561  # 2030 target not added
    assert rows[24600]["other_quantities"] is None
    # Only the correct join (via results_innovations_use) finds the hectares;
    # joining measures to result.id (13 Oct) finds nothing for 22751.
    assert rows[22751]["other_quantities"] == "160000.0 Area (ha)"


def test_semicolon_inside_a_string_literal_is_not_a_second_statement():
    assert pq._validate_sql("SELECT GROUP_CONCAT(name, '; ') FROM actor_type") is None
    assert pq._validate_sql("SELECT 'it''s; fine' FROM result;") is None
    assert pq._validate_sql("SELECT 1; SELECT 2") is not None
    assert pq._validate_sql("SELECT ';' ; DROP TABLE result") is not None


def test_recipe_11_runs_through_prms_query(full_db):
    out = _text(_query(_recipe_11_sql(), full_db))
    assert "171561" in out and "Area (ha)" in out


def _real_snapshot_with_use_tables():
    from synapsis.prms_snapshot import resolve_db_path
    path = resolve_db_path()
    if not os.path.isfile(path):
        return None
    if sc.check_schema(path).get("missing"):
        return None
    return path


def test_recipe_11_on_the_configured_snapshot():
    path = _real_snapshot_with_use_tables()
    if path is None:
        pytest.skip("no PRMS snapshot with the Innovation Use tables configured")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(_recipe_11_sql()))
    conn.close()
    assert len(rows) > 300  # 403 QAed 2025 Innovation Use codes on the June-2026 snapshot
    with_level = sum(r["use_level"] is not None for r in rows)
    assert with_level / len(rows) > 0.9
    assert all(r["use_level"] is None or 0 <= r["use_level"] <= 9 for r in rows)
    with_users = sum(r["users_current"] is not None for r in rows)
    assert with_users / len(rows) > 0.4
