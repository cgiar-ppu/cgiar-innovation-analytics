"""External view: free-text amounts, internal workflow data, authorizer hardening.

Verification round of the external partner role (Oct 2026):

* internal CLARISA project narratives / funder identifiers read as NULL for
  external roles (reporters typed project budgets into them);
* currency amounts inside every text value that ``prms_query`` /
  ``prms_search`` / the scenario and partner helpers hand to the model are
  redacted for external roles;
* internal PRMS workflow data that is not on the public Results Dashboard
  (account names, review / submission comments, QA log, revision history, AI
  drafts, notifications, deletion and backup copies) is refused or blanked for
  external roles;
* admins and researchers see exactly what they saw before;
* for every role, raw-storage virtual tables, ``pragma_database_list`` and a
  few dangerous SQL functions are refused.

Synthetic fixtures only: invented project names and amounts. The real-snapshot
section asserts only on counts and on the absence of amounts, never on values.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis import prms_access_policy as ap  # noqa: E402
from synapsis.auth.context import set_current_user_id  # noqa: E402

pq = importlib.import_module("synapsis.tools.prms_query")
ps = importlib.import_module("synapsis.tools.prms_search")
sa = importlib.import_module("synapsis.tools.scenario_analysis")
pi = importlib.import_module("synapsis.tools.partner_identification")

#: Synthetic amounts / sentinels that must never reach an external role.
SUMMARY = "The Example Valley pilot runs over five years with a budget of $77.7 million."
DESCRIPTION = "Phase two adds USD 4,321,000 for the Example Valley pilot (EUR 9.9 m co-funding)."
RESULT_DESC = ("Farmers in Example District adopted the drip kit; the programme invested "
               "US$ 6.6 million and 1,234 households use it on 5,678 ha since 2024 (45%).")
RESULT_TITLE = "Example seed fund of 3.3 million dollars launched"
ACCOUNT_NAME = "Zed"
REVIEW_COMMENT = "QA-COMMENT-SENTINEL please fix the indicator"
SUBMIT_COMMENT = "SUBMISSION-COMMENT-SENTINEL"
AMOUNT_STRINGS = ["77.7", "4,321,000", "9.9 m", "6.6 million", "3.3 million"]


def _make_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INTEGER, title TEXT,
            description TEXT, result_type_id INTEGER, is_active INTEGER, source TEXT,
            status_id INTEGER, reviewed_by INTEGER, created_by INTEGER);
        INSERT INTO result VALUES
            (1, 100, '{RESULT_TITLE}', '{RESULT_DESC}', 7, 1, 'Result', 2, 9, 7),
            (2, 101, 'Solar pumps', 'Pumps for 300 farms in 12 villages.', 7, 1, 'API', 6, NULL, 7),
            (3, 102, 'Seed policy', NULL, 1, 1, 'Result', 2, NULL, 7);
        CREATE TABLE clarisa_projects (id INTEGER PRIMARY KEY, short_name TEXT, full_name TEXT,
            summary TEXT, description TEXT, project_results TEXT, funder_code INTEGER,
            interim_director_review TEXT, modification_justification TEXT, total_budget DECIMAL);
        INSERT INTO clarisa_projects VALUES
            (1, 'PRJ-X', 'Example Valley pilot', '{SUMMARY}', '{DESCRIPTION}',
             'Inputs worth $1.1 million delivered.', 4242, 'Under review', 'Scope change', 777);
        CREATE TABLE clarisa_project_mappings (id INTEGER PRIMARY KEY, project_id INTEGER,
            program_code TEXT, comments TEXT, complementarity TEXT, efficiencies TEXT);
        INSERT INTO clarisa_project_mappings VALUES (1, 1, 'SP99', 'map comment', 'high', 'medium');
        CREATE TABLE non_pooled_project (id INTEGER PRIMARY KEY, grant_title TEXT,
            funder_institution_id INTEGER, center_grant_id TEXT, results_id INTEGER);
        INSERT INTO non_pooled_project VALUES (1, 'Example grant (USD 2.2 million)', 31, 'G-0001', 1);
        CREATE TABLE users (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT,
            email TEXT, password TEXT);
        INSERT INTO users VALUES (7, '{ACCOUNT_NAME}', 'Example', 'zed@example.invalid', 'pw');
        CREATE TABLE result_review_history (id INTEGER PRIMARY KEY, result_id INTEGER, comment TEXT);
        INSERT INTO result_review_history VALUES (1, 1, '{REVIEW_COMMENT}');
        CREATE TABLE submission (id INTEGER PRIMARY KEY, results_id INTEGER, comment TEXT);
        INSERT INTO submission VALUES (1, 1, '{SUBMIT_COMMENT}');
        CREATE TABLE result_qaed_log (id INTEGER PRIMARY KEY, result_id INTEGER, qaed_user INTEGER);
        INSERT INTO result_qaed_log VALUES (1, 1, 9);
        CREATE TABLE result_field_revision (id INTEGER PRIMARY KEY, result_id INTEGER, new_value TEXT);
        INSERT INTO result_field_revision VALUES (1, 1, 'rev');
        CREATE TABLE result_field_ai_state (id INTEGER PRIMARY KEY, result_id INTEGER, ai_suggestion TEXT);
        INSERT INTO result_field_ai_state VALUES (1, 1, 'draft');
        CREATE TABLE bilateral_quality_assessments (id INTEGER PRIMARY KEY, result_id INTEGER, verdict TEXT);
        INSERT INTO bilateral_quality_assessments VALUES (1, 2, 'ok');
        CREATE TABLE notifications (id INTEGER PRIMARY KEY, text TEXT);
        INSERT INTO notifications VALUES (1, 'n');
        CREATE TABLE share_result_request (id INTEGER PRIMARY KEY, result_id INTEGER);
        INSERT INTO share_result_request VALUES (1, 1);
        CREATE TABLE share_result_request_seen (id INTEGER PRIMARY KEY, request_id INTEGER);
        INSERT INTO share_result_request_seen VALUES (1, 1);
        CREATE TABLE result_deletion_audit (id INTEGER PRIMARY KEY, result_id INTEGER);
        INSERT INTO result_deletion_audit VALUES (1, 3);
        CREATE TABLE result_reactivation_backup_20990101 (id INTEGER PRIMARY KEY, title TEXT);
        INSERT INTO result_reactivation_backup_20990101 VALUES (1, 'backup');
        CREATE TABLE user_notification_settings (id INTEGER PRIMARY KEY, user_id INTEGER);
        INSERT INTO user_notification_settings VALUES (1, 7);
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def db(tmp_path) -> Path:
    return _make_db(tmp_path / "prdb.sqlite")


@pytest.fixture(autouse=True)
def _default_policy_toggles(monkeypatch):
    monkeypatch.delenv("IA_EXTERNAL_BLOCK_POLICY_AMOUNTS", raising=False)
    monkeypatch.delenv("IA_EXTERNAL_W12_ONLY", raising=False)


def _as(role: str, fn, *args, **kwargs):
    def _inner():
        set_current_user_id(f"u-{role}", role)
        return fn(*args, **kwargs)
    return contextvars.copy_context().run(_inner)


def _run(db: Path, sql: str, role):
    log = ap.AccessLog()
    rows, cols, _ = pq._execute_with_timeout(str(db), sql, timeout=5, access_log=log, role=role)
    return rows, cols, log


def _raw(db: Path, sql: str) -> list[dict]:
    """The rows without any policy (what a full-access role saw before)."""
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _query_as(role: str, db: Path, sql: str) -> tuple[bool, str]:
    def _call():
        with patch.object(pq, "PRMS_DB_PATH", str(db)):
            res = asyncio.run(pq.prms_query.handler({"sql": sql, "question": "t"}))
        return bool(res.get("is_error")), res["content"][0]["text"]
    return _as(role, _call)


def _no_amounts(text: str) -> bool:
    return ap.count_amounts(text) == 0 and not any(a in text for a in AMOUNT_STRINGS)


# ---------------------------------------------------------------------------
# 1. The amount pattern
# ---------------------------------------------------------------------------

AMOUNTS = [
    "$12.5 million", "$ 2,500", "$1.5bn", "$1-2 million", "$12 to 15 million", "$US 2.5",
    "USD 450,000", "USD5m", "USD 500k", "USD 5 000 000", "USD 3–5 m", "usd 40 thousand",
    "US$3m", "US $ 3.5 billion", "U.S. $2 million", "US-$ 4",
    "EUR 2 m", "€2m", "Euro 3 million", "Euro4.5 million", "2 million EUR", "3.4 million euros",
    "£300,000", "GBP 1.2 million", "10 million pounds sterling",
    "1,000,000 USD", "5k USD", "a 20,000-USD grant", "3.2  billion USD",
    "5 million US dollars", "20 million dollars", "7,500,000 dollars", "300 $/ha",
    "INR 450.5 million", "KES 1,200", "Rs. 4,500 crore",
]

NOT_AMOUNTS = [
    "In 2024, 1,016 innovations were reported", "45% of results", "2,000 ha of land",
    "IRL 7 scaling", "SP03 programme", "3.5 tonnes per ha", "10 m of canal", "200 km",
    "5 million farmers", "Europe 2025", "EUROPE 5", "BUSD 5", "funding in USD",
    "the 2015-2020 period", "US 5 states", "result 12345", "version 2.1", "Dollar Street",
    "Euro 2024 tournament", "a budget of USD", "SNPs rs12345 and rs678", "Tar-Rs-1 strain",
    "RSOC (5.2%)", "USDA 2020", "European Union 27", "the GBP panel", "1.2 million people",
]


class TestAmountPattern:

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_amount_is_redacted_inside_a_sentence(self, amount):
        text = f"The project (phase 2) received {amount} in 2025 for 300 farmers."
        out = ap.redact_amounts(text)
        assert ap.count_amounts(text) == 1, amount
        assert ap.AMOUNT_PLACEHOLDER in out
        assert "phase 2" in out and "in 2025 for 300 farmers" in out

    @pytest.mark.parametrize("text", NOT_AMOUNTS)
    def test_plain_numbers_are_left_alone(self, text):
        assert ap.redact_amounts(text) == text

    def test_two_amounts_and_a_year_before_a_currency(self):
        text = "In 2023 USD 5 million and EUR 3 million were committed."
        assert ap.redact_amounts(text) == (
            f"In 2023 {ap.AMOUNT_PLACEHOLDER} and {ap.AMOUNT_PLACEHOLDER} were committed.")

    @pytest.mark.parametrize("value", [None, 0, 12.5, b"$5 million"])
    def test_non_text_values_are_unchanged(self, value):
        assert ap.redact_amounts(value) is value

    def test_redact_rows_counts_and_leaves_input_untouched(self):
        rows = [{"a": SUMMARY, "b": 3, "c": None}, {"a": "no money", "b": 4, "c": DESCRIPTION}]
        log = ap.AccessLog()
        out = ap.redact_rows(rows, log)
        assert log.redacted_amounts == 3
        assert rows[0]["a"] == SUMMARY  # a new list, the input is not modified
        assert out[0]["b"] == 3 and out[0]["c"] is None and out[1]["a"] == "no money"
        assert all(_no_amounts(str(v)) for r in out for v in r.values())

    @pytest.mark.parametrize("role", ["admin", "researcher", None])
    def test_redact_for_role_is_a_no_op_for_full_access(self, role):
        rows = [{"a": SUMMARY}]
        assert ap.redact_for_role(rows, role) is rows


# ---------------------------------------------------------------------------
# 2. Internal project narratives and funder identifiers: NULL for externals
# ---------------------------------------------------------------------------

NARRATIVE_COLUMNS = [
    ("clarisa_projects", "summary"), ("clarisa_projects", "description"),
    ("clarisa_projects", "project_results"), ("clarisa_projects", "funder_code"),
    ("clarisa_projects", "interim_director_review"),
    ("clarisa_projects", "modification_justification"),
    ("clarisa_project_mappings", "comments"), ("clarisa_project_mappings", "complementarity"),
    ("clarisa_project_mappings", "efficiencies"),
    ("non_pooled_project", "funder_institution_id"), ("non_pooled_project", "center_grant_id"),
]


class TestNarrativesBlankedForExternal:

    @pytest.mark.parametrize("table,column", NARRATIVE_COLUMNS)
    def test_column_is_null_for_external_and_readable_for_full_access(self, db, table, column):
        sql = f"SELECT {column} AS v FROM {table}"
        ext, _, log = _run(db, sql, "external")
        assert ext == [{"v": None}]
        assert f"{table}.{column}" in log.financial_nulled
        for role in ("admin", "researcher"):
            full, _, flog = _run(db, sql, role)
            assert full == _raw(db, sql) and full[0]["v"] is not None
            assert not flog.nulled

    def test_excel_style_select_star_has_no_amount_for_external(self, db):
        for table in ("clarisa_projects", "clarisa_project_mappings", "non_pooled_project", "result"):
            rows, _, _ = _run(db, f"SELECT * FROM {table}", "external")
            assert rows, table
            for row in rows:
                for value in row.values():
                    assert _no_amounts(str(value)), (table, value)

    def test_names_and_codes_stay_usable(self, db):
        rows, _, _ = _run(db, "SELECT short_name, full_name FROM clarisa_projects", "external")
        assert rows == [{"short_name": "PRJ-X", "full_name": "Example Valley pilot"}]
        rows, _, _ = _run(db, "SELECT program_code FROM clarisa_project_mappings", "external")
        assert rows == [{"program_code": "SP99"}]

    def test_summary_cannot_be_probed_through_where(self, db):
        rows, _, _ = _run(db, "SELECT id FROM clarisa_projects WHERE summary LIKE '%budget%'", "external")
        assert rows == []


# ---------------------------------------------------------------------------
# 3. Amounts in other text values: redacted for externals, intact otherwise
# ---------------------------------------------------------------------------

class TestFreeTextAmounts:

    def test_result_description_and_title_are_redacted_for_external(self, db):
        rows, _, log = _run(db, "SELECT title, description FROM result WHERE id = 1", "external")
        assert ap.AMOUNT_PLACEHOLDER in rows[0]["description"]
        assert ap.AMOUNT_PLACEHOLDER in rows[0]["title"]
        assert _no_amounts(rows[0]["description"] + rows[0]["title"])
        # the non-money numbers of the same text survive
        assert "1,234 households" in rows[0]["description"]
        assert "5,678 ha since 2024 (45%)" in rows[0]["description"]
        assert log.redacted_amounts == 2

    def test_amounts_hidden_by_sql_functions_are_still_caught(self, db):
        rows, _, _ = _run(db, "SELECT upper(description) AS d, title || ' / ' || description AS t "
                              "FROM result WHERE id = 1", "external")
        assert _no_amounts(rows[0]["d"]) and _no_amounts(rows[0]["t"])

    def test_prms_query_output_for_external_has_placeholder_and_note(self, db):
        is_err, text = _query_as("external", db, "SELECT result_code, title, description FROM result")
        assert not is_err
        assert _no_amounts(text.split("\n---\nSQL executed")[0])
        assert ap.AMOUNT_PLACEHOLDER in text
        assert "currency amount(s) inside text values were replaced" in text

    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_full_access_rows_are_byte_identical_to_the_raw_rows(self, db, role):
        for sql in ("SELECT * FROM result ORDER BY id", "SELECT * FROM clarisa_projects",
                    "SELECT * FROM non_pooled_project", "SELECT * FROM clarisa_project_mappings"):
            rows, _, log = _run(db, sql, role)
            assert rows == _raw(db, sql)
            assert log.redacted_amounts == 0 and not log.nulled

    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_full_access_prms_query_text_keeps_the_amounts(self, db, role):
        is_err, text = _query_as(role, db, "SELECT title, description FROM result WHERE id = 1")
        assert not is_err
        assert "US$ 6.6 million" in text and "3.3 million dollars" in text
        assert ap.AMOUNT_PLACEHOLDER not in text and "external view" not in text


# ---------------------------------------------------------------------------
# 4. Internal workflow data (not on the public Results Dashboard)
# ---------------------------------------------------------------------------

INTERNAL_TABLES = [
    "result_qaed_log", "result_field_revision", "result_field_ai_state",
    "bilateral_quality_assessments", "notifications", "share_result_request",
    "share_result_request_seen", "result_deletion_audit",
    "result_reactivation_backup_20990101", "user_notification_settings",
]

INTERNAL_COLUMNS = [
    ("users", "first_name"), ("users", "last_name"), ("result_review_history", "comment"),
    ("submission", "comment"), ("result", "reviewed_by"),
]


class TestInternalWorkflowData:

    @pytest.mark.parametrize("table", INTERNAL_TABLES)
    def test_table_refused_for_external_with_the_external_view_message(self, db, table):
        for sql in (f"SELECT * FROM {table}", f"SELECT COUNT(*) FROM {table}"):
            with pytest.raises(ap.PRMSAccessDenied) as exc:
                _run(db, sql, "external")
            assert exc.value.external_view and not exc.value.financial
            assert ap.INTERNAL_DENIAL_MESSAGE in str(exc.value)
            assert exc.value.guidance == ap.INTERNAL_GUIDANCE

    @pytest.mark.parametrize("table", INTERNAL_TABLES)
    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_table_readable_for_full_access(self, db, table, role):
        rows, _, log = _run(db, f"SELECT COUNT(*) AS n FROM {table}", role)
        assert rows == [{"n": 1}] and not log.denied

    @pytest.mark.parametrize("table,column", INTERNAL_COLUMNS)
    def test_column_null_for_external_and_readable_for_full_access(self, db, table, column):
        sql = f"SELECT {column} AS v FROM {table} ORDER BY 1 DESC LIMIT 1"
        rows, _, log = _run(db, sql, "external")
        assert rows == [{"v": None}]
        assert f"{table}.{column}" in log.internal_nulled
        for role in ("admin", "researcher"):
            rows, _, _ = _run(db, sql, role)
            assert rows == _raw(db, sql) and rows[0]["v"] is not None

    def test_prms_query_messages(self, db):
        is_err, text = _query_as("external", db, "SELECT * FROM result_qaed_log")
        assert is_err and "Not available in this external view" in text
        assert ap.INTERNAL_GUIDANCE in text
        is_err, text = _query_as("external", db, "SELECT first_name, last_name FROM users")
        assert not is_err and ACCOUNT_NAME not in text
        assert "users.first_name, users.last_name returned empty (NULL) on purpose" in text
        assert ap.INTERNAL_DENIAL_MESSAGE in text
        is_err, text = _query_as("external", db, "SELECT comment FROM result_review_history "
                                                 "UNION ALL SELECT comment FROM submission")
        assert not is_err and REVIEW_COMMENT not in text and SUBMIT_COMMENT not in text

    def test_mixed_financial_and_internal_refusal_is_still_an_external_view_refusal(self, db, tmp_path):
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE result_initiative_budget (id INTEGER, current_year DECIMAL)")
        conn.commit()
        conn.close()
        with pytest.raises(ap.PRMSAccessDenied) as exc:
            _run(db, "SELECT * FROM result_initiative_budget, result_qaed_log", "external")
        # SQLite stops at the first refusal; whichever it is, it is an external-view refusal
        assert exc.value.external_view
        assert "credentials" not in str(exc.value)

    def test_result_rows_stay_usable_for_external(self, db):
        rows, _, _ = _run(db, "SELECT result_code, title, reviewed_by FROM result ORDER BY id", "external")
        assert [r["result_code"] for r in rows] == [100, 101, 102]
        assert all(r["reviewed_by"] is None for r in rows)

    def test_the_lists_are_lower_case_and_explained(self):
        for t, why in ap.INTERNAL_DENIED_TABLES.items():
            assert t == t.lower() and why
        for (t, c), why in ap.INTERNAL_NULLED_COLUMNS.items():
            assert t == t.lower() and c == c.lower() and why
        assert all(p == p.lower() for p in ap.INTERNAL_TABLE_PREFIXES)

    def test_blocked_internal_objects_matches_the_spec(self):
        assert set(ap.blocked_internal_objects()) == {
            "result_qaed_log", "result_field_revision", "result_field_ai_state",
            "bilateral_quality_assessments", "notifications", "result_deletion_audit",
            "user_notification_settings", "share_result_request*", "result_reactivation_backup_*",
            "users.first_name", "users.last_name", "result_review_history.comment",
            "submission.comment", "result.reviewed_by",
        }


# ---------------------------------------------------------------------------
# 5. The other entry points (search titles, scenario and partner helpers)
# ---------------------------------------------------------------------------

class TestOtherEntryPoints:

    def _format(self):
        hit = SimpleNamespace(result_code=100, title=RESULT_TITLE, result_type_id=7,
                              reported_year_id=2024, bm25_score=1.0, semantic_score=None,
                              rrf_score=0.5, matched_by="keyword", corpus_source="result")
        store = SimpleNamespace(codes=[100], model="m", snapshot="s")
        return ps._format_hits([hit], header="h", mode="keyword", eligible_size=None, store=store)

    def test_prms_search_titles_are_redacted_for_external(self):
        text = _as("external", self._format)
        assert _no_amounts(text)
        assert "Example seed fund of" in text

    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_prms_search_titles_unchanged_for_full_access(self, role):
        text = _as(role, self._format)
        assert RESULT_TITLE in text

    @pytest.mark.parametrize("module", [sa, pi])
    def test_helper_rows_are_redacted_for_external_only(self, db, module):
        def _call():
            with patch.object(module, "PRMS_DB_PATH", str(db)):
                conn = module._get_connection()
            try:
                return module._query_rows(conn, "SELECT title, description FROM result WHERE id = 1")
            finally:
                conn.close()
        ext = _as("external", _call)
        assert _no_amounts(ext[0]["title"] + ext[0]["description"])
        for role in ("admin", "researcher"):
            assert _as(role, _call) == _raw(db, "SELECT title, description FROM result WHERE id = 1")


# ---------------------------------------------------------------------------
# 6. Authorizer defence in depth (every role)
# ---------------------------------------------------------------------------

ALL_ROLES = [None, "admin", "researcher", "external"]


class TestDefenceInDepth:

    @pytest.mark.parametrize("role", ALL_ROLES)
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM pragma_database_list",
        "SELECT file FROM pragma_database_list",
        "SELECT name FROM dbstat",
        "SELECT COUNT(*) FROM dbstat",
        "SELECT fts3_tokenizer('simple')",
        "SELECT load_extension('x')",
    ])
    def test_refused_for_every_role(self, db, role, sql):
        with pytest.raises(sqlite3.DatabaseError):
            _run(db, sql, role)

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_raw_page_and_file_access_are_refused_by_the_authorizer(self, role):
        log = ap.AccessLog()
        auth = ap.make_authorizer(log, role)
        assert auth(sqlite3.SQLITE_READ, "sqlite_dbpage", "data", "main", None) == sqlite3.SQLITE_DENY
        assert auth(sqlite3.SQLITE_READ, "dbstat", "name", "main", None) == sqlite3.SQLITE_DENY
        assert auth(sqlite3.SQLITE_PRAGMA, "database_list", None, None, None) == sqlite3.SQLITE_DENY
        for fn in ("readfile", "writefile", "load_extension", "fts3_tokenizer"):
            assert auth(sqlite3.SQLITE_FUNCTION, None, fn, None, None) == sqlite3.SQLITE_DENY
        # schema browsing stays allowed
        assert auth(sqlite3.SQLITE_PRAGMA, "table_info", "result", None, None) == sqlite3.SQLITE_OK

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_schema_browsing_still_works(self, db, role):
        rows, _, _ = _run(db, "SELECT name FROM pragma_table_info('result')", role)
        assert "title" in {r["name"] for r in rows}
        rows, _, _ = _run(db, "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table'", role)
        assert rows[0]["n"] > 10

    def test_prms_query_refuses_database_list_with_a_neutral_message(self, db):
        is_err, text = _query_as("researcher", db, "SELECT * FROM pragma_database_list")
        assert is_err and "Not available" in text and str(db) not in text


# ---------------------------------------------------------------------------
# 7. Wording: the tool description is role-neutral, the prompt is role-gated
# ---------------------------------------------------------------------------

class TestWording:

    def test_prms_query_description_does_not_mention_the_external_view(self):
        desc = pq.prms_query.description
        assert "external" not in desc.lower()
        assert "financial" not in desc.lower() and "project budgets" not in desc.lower()

    def test_external_prompt_names_the_placeholder_and_internal_data(self):
        from synapsis.system_prompt import build_system_prompt

        prompt = build_system_prompt({}, role="external")
        assert ap.AMOUNT_PLACEHOLDER in prompt
        assert "Internal PRMS workflow data is not part of this view" in prompt

    @pytest.mark.parametrize("role", [None, "admin", "researcher"])
    def test_full_access_prompt_has_no_external_rules(self, role):
        from synapsis.system_prompt import build_system_prompt

        prompt = build_system_prompt({}, role=role)
        assert ap.AMOUNT_PLACEHOLDER not in prompt
        assert "external view" not in prompt.lower()


# ---------------------------------------------------------------------------
# 8. Real snapshot (skipped when the PRMS database is not available)
# ---------------------------------------------------------------------------

_REAL = pq.PRMS_DB_PATH if Path(pq.PRMS_DB_PATH).is_file() else None
real = pytest.mark.skipif(_REAL is None, reason="PRMS snapshot not available")


@real
class TestRealSnapshot:

    def _tables(self) -> set[str]:
        conn = sqlite3.connect(f"file:{_REAL}?mode=ro", uri=True)
        try:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()

    def test_every_blocked_internal_column_exists(self):
        conn = sqlite3.connect(f"file:{_REAL}?mode=ro", uri=True)
        try:
            for table, column in list(ap.INTERNAL_NULLED_COLUMNS) + NARRATIVE_COLUMNS:
                cols = {r[1] for r in conn.execute(f"SELECT * FROM pragma_table_info('{table}')")}
                assert column in cols, f"{table}.{column} missing from the snapshot"
        finally:
            conn.close()

    def test_internal_tables_present_in_the_snapshot_are_refused(self):
        tables = self._tables()
        present = [t for t in tables if ap.is_internal_table(t)]
        # the core ones exist in every vintage since Sep 2026
        assert {"result_qaed_log", "result_field_revision", "notifications"} <= set(present)
        for t in present:
            with pytest.raises(ap.PRMSAccessDenied):
                _run(Path(_REAL), f"SELECT COUNT(*) FROM {t}", "external")

    def test_project_narratives_are_null_for_external_only(self):
        sql = ("SELECT COUNT(summary) AS s, COUNT(description) AS d, COUNT(funder_code) AS f "
               "FROM clarisa_projects")
        ext, _, _ = _run(Path(_REAL), sql, "external")
        res, _, _ = _run(Path(_REAL), sql, "researcher")
        assert ext == [{"s": 0, "d": 0, "f": 0}]
        assert res[0]["s"] > 0 and res[0]["d"] > 0

    def test_select_star_clarisa_projects_has_no_amount_for_external(self):
        rows, _, _ = _run(Path(_REAL), "SELECT * FROM clarisa_projects", "external")
        assert rows
        assert sum(ap.count_amounts(v) for r in rows for v in r.values() if isinstance(v, str)) == 0

    def test_result_descriptions_with_amounts_are_redacted_for_external(self):
        sql = ("SELECT description FROM result WHERE description LIKE '%USD%' "
               "OR description LIKE '%$%' LIMIT 200")
        res, _, _ = _run(Path(_REAL), sql, "researcher")
        ext, _, log = _run(Path(_REAL), sql, "external")
        assert sum(ap.count_amounts(r["description"]) for r in res) > 0
        assert sum(ap.count_amounts(r["description"] or "") for r in ext) == 0
        assert log.redacted_amounts > 0

    @pytest.mark.parametrize("sql", [
        # headline innovation counts (development, use), partners, geographies
        "SELECT COUNT(DISTINCT result_code) AS n FROM result WHERE result_type_id IN (2,7,10) "
        "AND is_active = 1 AND ((source='Result' AND status_id=2) OR (source='API' AND status_id=6))",
        "SELECT reported_year_id AS y, COUNT(DISTINCT result_code) AS n FROM result "
        "WHERE result_type_id = 2 AND is_active = 1 GROUP BY 1 ORDER BY 1",
        "SELECT COUNT(DISTINCT rbi.institutions_id) AS n FROM results_by_institution rbi "
        "JOIN result r ON r.id = rbi.result_id WHERE rbi.is_active = 1",
        "SELECT COUNT(DISTINCT rc.country_id) AS n FROM result_country rc "
        "JOIN result r ON r.id = rc.result_id WHERE r.result_type_id = 7",
    ])
    def test_headline_answers_identical_for_external_and_researcher(self, sql):
        ext, _, log = _run(Path(_REAL), sql, "external")
        res, _, _ = _run(Path(_REAL), sql, "researcher")
        assert ext == res and ext
        assert not log.denied and not log.nulled


# ---------------------------------------------------------------------------
# 9. "PRMS" evidence label reads "Factual" everywhere it is shown or instructed
# ---------------------------------------------------------------------------

def test_no_prompt_tool_or_reference_still_prints_the_old_prms_validated_tag():
    """Marc (9 Oct): the PRMS label on factual evidence reads "Factual". The tag
    is now ``[Factual · PRMS]`` (PRMS stays in citations and Sources)."""
    repo = Path(__file__).resolve().parents[1]
    paths = [*(repo / "synapsis").rglob("*.py"), *(repo / "references").rglob("*.md"),
             repo / "docs" / "user-guide.md"]
    offenders = []
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "PRMS-VALIDATED" in line.upper() and not line.lstrip().startswith("#"):
                offenders.append(f"{p.relative_to(repo)}:{n}")
    assert offenders == []


def test_specialists_and_tools_use_the_factual_tag():
    from synapsis.agents import definitions

    text = Path(definitions.__file__).read_text(encoding="utf-8")
    assert "[Factual · PRMS]" in text
    assert "[Factual · PRMS]" in Path(sa.__file__).read_text(encoding="utf-8")
    assert "[Factual · PRMS]" in Path(pi.__file__).read_text(encoding="utf-8")
