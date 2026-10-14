"""The PRMS access policy: credential / personal-contact tables and columns are
not readable through the free-SQL tools (prms_query, prms_search filter_sql).

Synthetic fixture first (always runs); a real-snapshot section runs when the
PRMS database is available and checks that analytic queries are untouched.
Tests never print or assert on real values of restricted objects — only on
synthetic sentinels, counts of NULLs and error texts.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis import prms_access_policy as ap  # noqa: E402
import importlib  # noqa: E402

# synapsis.tools re-exports the tool objects under the module names, so fetch
# the modules themselves.
pq = importlib.import_module("synapsis.tools.prms_query")
ps = importlib.import_module("synapsis.tools.prms_search")

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "SENTINEL-DO-NOT-LEAK"


# ---------------------------------------------------------------------------
# Synthetic snapshot
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INTEGER, title TEXT,
                             created_by INTEGER, is_active INTEGER);
        INSERT INTO result VALUES (1, 100, 'Drought-tolerant maize', 7, 1),
                                  (2, 101, 'Solar pumps', 8, 1);
        CREATE TABLE users (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
                            password TEXT, email TEXT, is_cgiar INTEGER);
        INSERT INTO users VALUES (7, 'Ada', 'Lovelace', '{SENTINEL}-pw', 'ada@{SENTINEL}.org', 1),
                                 (8, 'Alan', 'Turing', NULL, 'alan@{SENTINEL}.org', 0);
        CREATE TABLE global_parameters (id INTEGER PRIMARY KEY, name TEXT, value TEXT);
        INSERT INTO global_parameters VALUES (1, 'some_setting', '{SENTINEL}-value');
        CREATE TABLE token_report_bi (id INTEGER PRIMARY KEY, token_bi TEXT);
        INSERT INTO token_report_bi VALUES (1, '{SENTINEL}-token');
        CREATE TABLE otp_challenges (id INTEGER PRIMARY KEY, code_hmac TEXT);
        CREATE TABLE webhook_endpoint (id INTEGER PRIMARY KEY, url TEXT, secret TEXT);
        CREATE TABLE ad_users (id INTEGER PRIMARY KEY, mail TEXT, sam_account_name TEXT);
        INSERT INTO ad_users VALUES (1, 'x@{SENTINEL}.org', '{SENTINEL}-login');
        CREATE TABLE result_ip_expert (result_ip_expert_id INTEGER PRIMARY KEY, result_id INTEGER,
                                       first_name TEXT, last_name TEXT, email TEXT);
        INSERT INTO result_ip_expert VALUES (1, 1, 'Grace', 'Hopper', 'grace@{SENTINEL}.org');
        CREATE TABLE intellectual_property_experts (ip_expert_id INTEGER PRIMARY KEY,
                                                    first_name TEXT, email TEXT);
        INSERT INTO intellectual_property_experts VALUES (1, 'Katherine', 'kj@{SENTINEL}.org');
        CREATE TABLE result_ip_expert_workshop_organized (id INTEGER PRIMARY KEY, result_id INTEGER,
                                                          first_name TEXT, email TEXT);
        INSERT INTO result_ip_expert_workshop_organized VALUES (1, 1, 'Mary', 'mj@{SENTINEL}.org');
        -- views created by the snapshot itself must not be a way round the policy
        CREATE VIEW v_params AS SELECT name, value FROM global_parameters;
        CREATE VIEW v_people AS SELECT first_name, email FROM users;
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def db(tmp_path) -> Path:
    return _make_db(tmp_path / "prdb.sqlite")


def _run(db: Path, sql: str, role=pq.CALLER_ROLE):
    log = ap.AccessLog()
    rows, cols, n = pq._execute_with_timeout(str(db), sql, timeout=5, access_log=log, role=role)
    return rows, cols, log


def _query(db: Path, sql: str) -> tuple[bool, str]:
    with patch.object(pq, "PRMS_DB_PATH", str(db)):
        res = asyncio.run(pq.prms_query.handler({"sql": sql, "question": "t"}))
    return bool(res.get("is_error")), res["content"][0]["text"]


# ---------------------------------------------------------------------------
# 1. Whole tables are refused — including COUNT(*), EXISTS, rowid, views
# ---------------------------------------------------------------------------

DENIED_SQL = [
    "SELECT COUNT(*) FROM global_parameters",
    "SELECT * FROM global_parameters",
    "SELECT value FROM global_parameters WHERE name = 'some_setting'",
    "SELECT EXISTS (SELECT 1 FROM token_report_bi)",
    "SELECT rowid FROM token_report_bi",
    'SELECT COUNT(*) FROM "Global_Parameters"',
    "SELECT r.title FROM result r JOIN global_parameters g ON g.id = r.id",
    "SELECT title FROM result WHERE id IN (SELECT id FROM ad_users)",
    "WITH t AS (SELECT token_bi FROM token_report_bi) SELECT COUNT(*) FROM t",
    "SELECT COUNT(*) FROM otp_challenges",
    "SELECT COUNT(*) FROM webhook_endpoint",
    "SELECT mail FROM ad_users",
    "SELECT * FROM v_params",
]


class TestDeniedTables:

    @pytest.mark.parametrize("sql", DENIED_SQL)
    def test_refused_with_clear_message(self, db, sql):
        with pytest.raises(ap.PRMSAccessDenied) as exc:
            _run(db, sql)
        assert ap.DENIAL_MESSAGE in str(exc.value)
        assert SENTINEL not in str(exc.value)

    @pytest.mark.parametrize("sql", DENIED_SQL[:4])
    def test_prms_query_returns_a_neutral_error(self, db, sql):
        is_err, text = _query(db, sql)
        assert is_err
        assert ap.DENIAL_MESSAGE in text
        assert SENTINEL not in text
        assert "not authorized" not in text  # SQLite's bare wording is replaced

    def test_prms_search_filter_sql_is_covered_too(self, db):
        with patch.object(ps, "PRMS_DB_PATH", str(db)):
            eligible, err = ps._resolve_eligible(
                "SELECT id AS result_code FROM global_parameters", None)
        assert eligible is None
        assert err and ap.DENIAL_MESSAGE in err
        assert SENTINEL not in err

    def test_total_count_helper_cannot_count_a_denied_table(self, db):
        assert pq._get_total_count(str(db), "SELECT * FROM token_report_bi") is None


# ---------------------------------------------------------------------------
# 2. Contact / credential columns read as NULL; the rest of the table works
# ---------------------------------------------------------------------------

class TestNulledColumns:

    def test_select_star_works_and_blanks_only_the_listed_columns(self, db):
        # A full-access role: account names are blanked for external roles
        # (see test_external_view_freetext.py), credentials for everyone.
        rows, cols, log = _run(db, "SELECT * FROM users ORDER BY id", "researcher")
        assert cols == ["id", "first_name", "last_name", "password", "email", "is_cgiar"]
        assert [r["first_name"] for r in rows] == ["Ada", "Alan"]
        assert all(r["email"] is None and r["password"] is None for r in rows)
        assert set(log.nulled) == {"users.email", "users.password"}
        assert not log.denied

    def test_where_like_cannot_probe_values(self, db):
        rows, _, _ = _run(db, f"SELECT COUNT(*) AS n FROM users WHERE email LIKE '%{SENTINEL}%'")
        assert rows[0]["n"] == 0
        rows, _, _ = _run(db, "SELECT COUNT(email) AS n, COUNT(password) AS p, COUNT(*) AS t FROM users")
        assert (rows[0]["n"], rows[0]["p"], rows[0]["t"]) == (0, 0, 2)

    def test_aliases_ctes_views_and_functions_are_covered(self, db):
        for sql in (
            "SELECT u.email AS e FROM users u",
            "WITH x AS (SELECT email AS e FROM users) SELECT e FROM x",
            "SELECT UPPER(email) AS e FROM users",
            "SELECT email AS e FROM v_people",
            "SELECT e.email AS e FROM result r JOIN result_ip_expert e ON e.result_id = r.id",
            "SELECT email AS e FROM intellectual_property_experts",
            "SELECT email AS e FROM result_ip_expert_workshop_organized",
        ):
            rows, _, log = _run(db, sql)
            assert rows and all(r["e"] is None for r in rows), sql
            assert log.nulled, sql

    def test_names_of_ip_experts_stay_available(self, db):
        rows, _, _ = _run(db, "SELECT first_name, last_name FROM result_ip_expert")
        assert rows == [{"first_name": "Grace", "last_name": "Hopper"}]

    def test_prms_query_says_the_blank_is_deliberate(self, db):
        is_err, text = _query(db, "SELECT * FROM users")
        assert not is_err
        assert "users.email" in text and "on purpose" in text
        assert SENTINEL not in text

    def test_joining_users_for_creator_names_still_works(self, db):
        rows, _, log = _run(
            db,
            "SELECT r.result_code, u.first_name || ' ' || u.last_name AS creator "
            "FROM result r JOIN users u ON u.id = r.created_by ORDER BY r.result_code",
            "researcher",
        )
        assert [r["creator"] for r in rows] == ["Ada Lovelace", "Alan Turing"]
        assert not log.nulled and not log.denied


# ---------------------------------------------------------------------------
# 3. Schema browsing and ordinary queries are untouched
# ---------------------------------------------------------------------------

class TestUntouched:

    def test_schema_browsing_is_allowed(self, db):
        rows, _, _ = _run(db, "SELECT name FROM pragma_table_info('global_parameters')")
        assert [r["name"] for r in rows] == ["id", "name", "value"]
        rows, _, _ = _run(db, "SELECT COUNT(*) AS n FROM sqlite_master WHERE name = 'users'")
        assert rows[0]["n"] == 1

    def test_ordinary_query_has_no_note(self, db):
        is_err, text = _query(db, "SELECT result_code, title FROM result")
        assert not is_err
        assert "on purpose" not in text and ap.DENIAL_MESSAGE not in text


class TestAuthorizerDirect:

    def test_attach_and_extension_loading_are_denied(self, tmp_path, db):
        conn = sqlite3.connect(str(db))
        log = ap.install(conn)
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"ATTACH DATABASE '{tmp_path / 'other.sqlite'}' AS o")
        with pytest.raises(sqlite3.Error):
            conn.execute("SELECT load_extension('x')")
        conn.close()
        assert "ATTACH/DETACH" in log.denied

    def test_the_lists_are_lower_case_and_explained(self):
        for t, why in ap.DENIED_TABLES.items():
            assert t == t.lower() and why
        for (t, c), why in ap.NULLED_COLUMNS.items():
            assert t == t.lower() and c == c.lower() and why

    def test_no_reference_recipe_reads_a_restricted_object(self):
        """The agent's references must never teach SQL that the policy refuses."""
        text = "\n".join(
            p.read_text(encoding="utf-8") for p in (REPO / "references").glob("*.md")
        )
        used = {m.lower() for m in re.findall(r"\b(?:FROM|JOIN)\s+[`\"]?(\w+)", text, re.I)}
        assert not (used & set(ap.DENIED_TABLES)), used & set(ap.DENIED_TABLES)
        for t, c in ap.NULLED_COLUMNS:
            assert not re.search(rf"\b{t}\.{c}\b", text.replace("`", "")), f"{t}.{c}"


# ---------------------------------------------------------------------------
# 4. Real snapshot (runs when PRMS data is available)
# ---------------------------------------------------------------------------

def _real_tables() -> set[str]:
    if not os.path.isfile(pq.PRMS_DB_PATH):
        return set()
    try:
        conn = sqlite3.connect(f"file:{pq.PRMS_DB_PATH}?mode=ro", uri=True)
        try:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


_REAL = _real_tables()
requires_real = pytest.mark.skipif(not _REAL, reason="PRMS snapshot not available")

ANALYTIC_QUERIES = [
    "SELECT COUNT(*) AS n FROM result",
    "SELECT result_type_id, COUNT(DISTINCT result_code) AS n FROM result "
    "WHERE is_active = 1 GROUP BY result_type_id ORDER BY result_type_id",
    "SELECT c.iso_alpha_3, COUNT(*) AS n FROM result_country rc "
    "JOIN clarisa_countries c ON c.id = rc.country_id GROUP BY c.iso_alpha_3 "
    "ORDER BY n DESC, c.iso_alpha_3 LIMIT 5",
    "SELECT COUNT(*) AS n FROM results_by_institution_type WHERE institution_roles_id = 5",
    "SELECT COUNT(*) AS n FROM result_ip_measure WHERE is_active = 1",
    "SELECT COUNT(lead_contact_person) AS n FROM result",
    "SELECT COUNT(*) AS n FROM result_ip_expert",
]


@requires_real
class TestRealSnapshot:

    @pytest.mark.parametrize("table", sorted(ap.DENIED_TABLES))
    def test_denied_tables_refuse_even_a_count(self, table):
        if table not in _REAL:
            pytest.skip(f"{table} not in this snapshot")
        is_err, text = _query(Path(pq.PRMS_DB_PATH), f"SELECT COUNT(*) FROM {table}")
        assert is_err and ap.DENIAL_MESSAGE in text

    @pytest.mark.parametrize("tc", sorted(ap.NULLED_COLUMNS))
    def test_nulled_columns_count_zero(self, tc):
        table, column = tc
        if table not in _REAL:
            pytest.skip(f"{table} not in this snapshot")
        rows, _, log = _run(Path(pq.PRMS_DB_PATH), f"SELECT COUNT({column}) AS n FROM {table}")
        assert rows[0]["n"] == 0
        assert f"{table}.{column}" in log.nulled

    @pytest.mark.parametrize("sql", ANALYTIC_QUERIES)
    def test_analytic_queries_give_the_same_answer_with_and_without_the_policy(self, sql):
        first = sql.split("FROM")[1].split()[0]
        if first not in _REAL:
            pytest.skip(f"{first} not in this snapshot")
        conn = sqlite3.connect(f"file:{pq.PRMS_DB_PATH}?mode=ro", uri=True)
        try:
            plain = [tuple(r) for r in conn.execute(sql).fetchall()]
        finally:
            conn.close()
        rows, cols, log = _run(Path(pq.PRMS_DB_PATH), sql)
        assert [tuple(r[c] for c in cols) for r in rows] == plain
        assert not log.denied and not log.nulled


def test_the_snapshot_file_itself_is_not_readable_with_read_glob_grep():
    """Belt and braces: the policy above guards SQL; the sandbox path hook must
    keep the agent away from the database file (any *.sqlite) as well."""
    from synapsis.hooks import sandbox

    for name in ("prdb.sqlite", "prdb.sqlite-wal", "prdb.sqlite-shm", "prdb.sqlite-journal",
                 "prms_corpus.sqlite", "x.sqlite3-wal"):
        assert sandbox.path_denial(Path("/app/data") / name)
    assert sandbox.path_denial(Path(os.path.realpath(pq.PRMS_DB_PATH))) or not str(
        pq.PRMS_DB_PATH).endswith((".sqlite", ".db"))
