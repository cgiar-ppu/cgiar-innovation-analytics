"""External partner role: budget / financial data blocked at query level.

Item 5 of the Innovation Analytics MVP test release: a separate ``external``
role whose accounts cannot read budget or financial figures — enforced in the
SQLite authorizer every PRMS entry point uses (``prms_query``, ``prms_search``
``filter_sql``, the scenario / partner helpers), so the model cannot reveal the
values in answers, summaries or downloads. Admins and researchers keep the
full analytic snapshot.

Synthetic fixture first (always runs); a real-snapshot section runs when the
PRMS database is available. Tests assert only on synthetic sentinels, NULL
counts and message texts — never on real financial values.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import os
import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis import prms_access_policy as ap  # noqa: E402
from synapsis.auth.context import set_current_user_id  # noqa: E402
from synapsis.utils.responses import success_response  # noqa: E402

pq = importlib.import_module("synapsis.tools.prms_query")
ps = importlib.import_module("synapsis.tools.prms_search")
sa = importlib.import_module("synapsis.tools.scenario_analysis")
pi = importlib.import_module("synapsis.tools.partner_identification")

REPO = Path(__file__).resolve().parents[1]
#: A synthetic amount that must never appear in any external-role output.
MONEY = 987654321
MONEY_TXT = "987654321"


# ---------------------------------------------------------------------------
# Synthetic snapshot
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INTEGER, title TEXT,
                             result_type_id INTEGER, is_active INTEGER);
        INSERT INTO result VALUES (1, 100, 'Drought-tolerant maize', 7, 1),
                                  (2, 101, 'Solar pumps', 7, 1),
                                  (3, 102, 'Seed policy', 1, 1);
        CREATE TABLE results_by_inititiative (id INTEGER PRIMARY KEY, result_id INTEGER,
                                              inititiative_id INTEGER);
        INSERT INTO results_by_inititiative VALUES (10, 1, 5), (11, 2, 5);
        CREATE TABLE result_initiative_budget (result_initiative_budget_id INTEGER PRIMARY KEY,
            result_initiative_id INTEGER, current_year DECIMAL, next_year DECIMAL, kind_cash DECIMAL,
            is_active INTEGER);
        INSERT INTO result_initiative_budget VALUES (1, 10, {MONEY}, {MONEY}, {MONEY}, 1);
        CREATE TABLE result_institutions_budget (result_institutions_budget_id INTEGER PRIMARY KEY,
            result_institution_id INTEGER, in_kind DECIMAL, in_cash DECIMAL, kind_cash DECIMAL);
        INSERT INTO result_institutions_budget VALUES (1, 1, {MONEY}, {MONEY}, {MONEY});
        CREATE TABLE non_pooled_projetct_budget (non_pooled_projetct_budget_id INTEGER PRIMARY KEY,
            non_pooled_projetct_id INTEGER, in_kind DECIMAL, in_cash DECIMAL, kind_cash DECIMAL);
        INSERT INTO non_pooled_projetct_budget VALUES (1, 1, {MONEY}, {MONEY}, {MONEY});
        CREATE TABLE clarisa_projects (id INTEGER PRIMARY KEY, short_name TEXT, full_name TEXT,
            total_budget DECIMAL, remaining DECIMAL, annual DECIMAL, source_of_funding TEXT,
            funder_code INTEGER);
        INSERT INTO clarisa_projects VALUES (1, 'PRJ-A', 'Project A', {MONEY}, {MONEY}, {MONEY},
                                             'FUNDER-{MONEY_TXT}', 42),
                                            (2, 'PRJ-B', 'Project B', {MONEY}, NULL, NULL, NULL, 43);
        CREATE TABLE clarisa_project_mappings (id INTEGER PRIMARY KEY, project_id INTEGER,
            program_id INTEGER, allocation DECIMAL, program_code TEXT);
        INSERT INTO clarisa_project_mappings VALUES (1, 1, 3, {MONEY}, 'SP03');
        CREATE TABLE clarisa_project_countries (id INTEGER PRIMARY KEY, project_id INTEGER,
            country_id INTEGER, allocation_percentage DECIMAL);
        INSERT INTO clarisa_project_countries VALUES (1, 1, 404, {MONEY});
        CREATE TABLE results_toc_result (result_toc_result_id INTEGER PRIMARY KEY, results_id INTEGER,
            toc_result_id INTEGER, program_invested_financial_resources INTEGER);
        INSERT INTO results_toc_result VALUES (1, 1, 77, 1);
        CREATE TABLE results_policy_changes (result_policy_change_id INTEGER PRIMARY KEY,
            result_id INTEGER, amount FLOAT, status_amount TEXT, policy_type_id INTEGER);
        INSERT INTO results_policy_changes VALUES (1, 3, {MONEY}, 'Confirmed-{MONEY_TXT}', 1);
        CREATE TABLE users (id INTEGER PRIMARY KEY, first_name TEXT, password TEXT, email TEXT);
        INSERT INTO users VALUES (7, 'Ada', 'pw-secret', 'ada@example.invalid');
        CREATE TABLE global_parameters (id INTEGER PRIMARY KEY, name TEXT, value TEXT);
        INSERT INTO global_parameters VALUES (1, 'some_setting', 'value-secret');
        -- a view over a budget table must not be a way round the policy
        CREATE VIEW v_budget AS SELECT result_initiative_id, current_year FROM result_initiative_budget;
        CREATE VIEW v_projects AS SELECT short_name, total_budget FROM clarisa_projects;
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
    """Run *fn* in a fresh context signed in with *role* (like a chat socket)."""
    def _inner():
        set_current_user_id(f"u-{role}", role)
        return fn(*args, **kwargs)
    return contextvars.copy_context().run(_inner)


def _run(db: Path, sql: str, role):
    log = ap.AccessLog()
    rows, cols, _ = pq._execute_with_timeout(str(db), sql, timeout=5, access_log=log, role=role)
    return rows, cols, log


def _query_as(role: str, db: Path, sql: str) -> tuple[bool, str]:
    def _call():
        with patch.object(pq, "PRMS_DB_PATH", str(db)):
            res = asyncio.run(pq.prms_query.handler({"sql": sql, "question": "t"}))
        return bool(res.get("is_error")), res["content"][0]["text"]
    return _as(role, _call)


# ---------------------------------------------------------------------------
# 1. Roles: who is restricted
# ---------------------------------------------------------------------------

class TestRoles:

    @pytest.mark.parametrize("role", ["admin", "researcher", "Researcher", " admin "])
    def test_full_access_roles_are_not_restricted(self, role):
        assert not ap.is_restricted(role)

    @pytest.mark.parametrize("role", ["external", "user", "", "guest", "invited"])
    def test_every_other_role_is_restricted_fail_closed(self, role):
        assert ap.is_restricted(role)

    def test_no_role_means_base_policy_only(self):
        assert not ap.is_restricted(None)

    def test_caller_role_reads_the_verified_context(self):
        assert _as("external", ap.caller_role) == "external"
        assert _as("researcher", ap.caller_role) == "researcher"

    def test_blocked_list_matches_the_spec(self):
        blocked = set(ap.blocked_financial_objects())
        assert {
            "result_initiative_budget", "result_institutions_budget", "non_pooled_projetct_budget",
            "clarisa_projects.total_budget", "clarisa_projects.remaining", "clarisa_projects.annual",
            "clarisa_projects.source_of_funding", "clarisa_project_mappings.allocation",
            "clarisa_project_countries.allocation_percentage",
            "results_toc_result.program_invested_financial_resources",
            "results_policy_changes.amount", "results_policy_changes.status_amount",
        } == blocked


# ---------------------------------------------------------------------------
# 2. External role: budget tables refused, financial columns NULL
# ---------------------------------------------------------------------------

DENIED_FOR_EXTERNAL = [
    "SELECT COUNT(*) FROM result_initiative_budget",
    "SELECT * FROM result_initiative_budget",
    "SELECT SUM(current_year) FROM result_initiative_budget",
    "SELECT in_cash FROM result_institutions_budget",
    "SELECT kind_cash FROM non_pooled_projetct_budget",
    'SELECT COUNT(*) FROM "Result_Initiative_Budget"',
    "SELECT EXISTS (SELECT 1 FROM result_initiative_budget WHERE current_year > 1000)",
    "SELECT r.title FROM result r JOIN results_by_inititiative b ON b.result_id = r.id "
    "JOIN result_initiative_budget g ON g.result_initiative_id = b.id",
    "WITH t AS (SELECT current_year FROM result_initiative_budget) SELECT MAX(current_year) FROM t",
    "SELECT title FROM result WHERE id IN (SELECT result_institution_id FROM result_institutions_budget)",
    "SELECT * FROM v_budget",
]


class TestExternalDenied:

    @pytest.mark.parametrize("sql", DENIED_FOR_EXTERNAL)
    def test_refused_with_the_external_view_message(self, db, sql):
        with pytest.raises(ap.PRMSAccessDenied) as exc:
            _run(db, sql, "external")
        assert exc.value.financial is True
        assert ap.FINANCIAL_DENIAL_MESSAGE in str(exc.value)
        assert MONEY_TXT not in str(exc.value)

    @pytest.mark.parametrize("sql", DENIED_FOR_EXTERNAL[:5])
    def test_prms_query_declines_politely_not_as_missing_data(self, db, sql):
        is_err, text = _query_as("external", db, sql)
        assert is_err
        assert "not available in this external view" in text
        assert "isn't available in this external view" in text      # guidance to the model
        assert "do not call it missing" in text
        assert MONEY_TXT not in text
        assert "not authorized" not in text

    def test_mixed_credential_and_budget_statement_uses_the_credential_message(self, db):
        with pytest.raises(ap.PRMSAccessDenied) as exc:
            _run(db, "SELECT (SELECT COUNT(*) FROM global_parameters), "
                     "(SELECT COUNT(*) FROM result_initiative_budget)", "external")
        assert exc.value.financial is False
        assert ap.DENIAL_MESSAGE in str(exc.value)

    def test_total_count_helper_cannot_count_a_budget_table(self, db):
        assert pq._get_total_count(str(db), "SELECT * FROM result_initiative_budget",
                                   role="external") is None


NULLED_FOR_EXTERNAL = [
    ("SELECT total_budget FROM clarisa_projects", "clarisa_projects.total_budget"),
    ("SELECT remaining, annual FROM clarisa_projects", "clarisa_projects.remaining"),
    ("SELECT source_of_funding FROM clarisa_projects", "clarisa_projects.source_of_funding"),
    ("SELECT allocation FROM clarisa_project_mappings", "clarisa_project_mappings.allocation"),
    ("SELECT allocation_percentage FROM clarisa_project_countries",
     "clarisa_project_countries.allocation_percentage"),
    ("SELECT program_invested_financial_resources FROM results_toc_result",
     "results_toc_result.program_invested_financial_resources"),
    ("SELECT amount, status_amount FROM results_policy_changes", "results_policy_changes.amount"),
    ("SELECT short_name, total_budget FROM v_projects", "clarisa_projects.total_budget"),
]


class TestExternalNulled:

    @pytest.mark.parametrize("sql,col", NULLED_FOR_EXTERNAL)
    def test_financial_columns_read_as_null(self, db, sql, col):
        rows, _, log = _run(db, sql, "external")
        assert rows
        for row in rows:
            assert all(v is None for k, v in row.items() if k != "short_name")
        assert col in log.financial_nulled
        assert MONEY_TXT not in repr(rows)

    def test_rest_of_the_project_tables_stays_usable(self, db):
        rows, _, _ = _run(db, "SELECT * FROM clarisa_projects ORDER BY id", "external")
        assert [r["short_name"] for r in rows] == ["PRJ-A", "PRJ-B"]
        assert [r["funder_code"] for r in rows] == [42, 43]
        assert all(r["total_budget"] is None and r["source_of_funding"] is None for r in rows)
        rows, _, _ = _run(db, "SELECT program_code FROM clarisa_project_mappings", "external")
        assert rows == [{"program_code": "SP03"}]

    @pytest.mark.parametrize("sql", [
        "SELECT short_name FROM clarisa_projects WHERE total_budget > 1000",
        "SELECT short_name FROM clarisa_projects WHERE CAST(total_budget AS TEXT) LIKE '9%'",
        "SELECT short_name FROM clarisa_projects WHERE source_of_funding LIKE 'FUNDER%'",
        "SELECT project_id FROM clarisa_project_mappings WHERE allocation BETWEEN 1 AND 1e12",
        "SELECT result_id FROM results_policy_changes WHERE amount > 0",
    ])
    def test_values_cannot_be_probed_through_where(self, db, sql):
        rows, _, _ = _run(db, sql, "external")
        assert rows == []

    def test_aggregates_over_blanked_columns_are_null(self, db):
        rows, _, _ = _run(db, "SELECT SUM(total_budget) AS s, MAX(allocation) AS m FROM clarisa_projects "
                              "JOIN clarisa_project_mappings ON project_id = clarisa_projects.id", "external")
        assert rows == [{"s": None, "m": None}]

    def test_prms_query_adds_the_external_view_note(self, db):
        is_err, text = _query_as("external", db, "SELECT short_name, total_budget FROM clarisa_projects")
        assert not is_err
        assert "PRJ-A" in text
        assert MONEY_TXT not in text
        assert "clarisa_projects.total_budget returned empty (NULL) on purpose" in text
        assert ap.FINANCIAL_DENIAL_MESSAGE in text
        assert "isn't available in this external view" in text

    def test_policy_amounts_toggle(self, db, monkeypatch):
        monkeypatch.setenv("IA_EXTERNAL_BLOCK_POLICY_AMOUNTS", "false")
        rows, _, _ = _run(db, "SELECT amount FROM results_policy_changes", "external")
        assert rows == [{"amount": float(MONEY)}]
        # the core financial objects stay blocked whatever the toggle
        with pytest.raises(ap.PRMSAccessDenied):
            _run(db, "SELECT COUNT(*) FROM result_initiative_budget", "external")

    def test_analytic_tables_are_untouched(self, db):
        rows, _, log = _run(db, "SELECT COUNT(DISTINCT result_code) AS n FROM result "
                                "WHERE result_type_id = 7", "external")
        assert rows == [{"n": 2}]
        assert not log.denied and not log.nulled

    def test_schema_browsing_stays_allowed(self, db):
        rows, _, _ = _run(db, "SELECT name FROM pragma_table_info('clarisa_projects')", "external")
        assert "total_budget" in {r["name"] for r in rows}


# ---------------------------------------------------------------------------
# 3. Admins and researchers: unchanged
# ---------------------------------------------------------------------------

class TestFullAccessUnchanged:

    @pytest.mark.parametrize("role", ["admin", "researcher", None])
    def test_budget_tables_readable(self, db, role):
        rows, _, log = _run(db, "SELECT current_year FROM result_initiative_budget", role)
        assert rows == [{"current_year": MONEY}]
        assert not log.denied and not log.financial_nulled

    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_financial_columns_readable(self, db, role):
        rows, _, _ = _run(db, "SELECT total_budget, source_of_funding FROM clarisa_projects WHERE id = 1", role)
        assert rows == [{"total_budget": MONEY, "source_of_funding": f"FUNDER-{MONEY_TXT}"}]

    @pytest.mark.parametrize("role", ["admin", "researcher"])
    def test_prms_query_returns_the_values(self, db, role):
        is_err, text = _query_as(role, db, "SELECT SUM(current_year) AS s FROM result_initiative_budget")
        assert not is_err
        assert MONEY_TXT in text
        assert "external view" not in text

    @pytest.mark.parametrize("role", ["admin", "researcher", "external"])
    def test_credential_policy_applies_to_every_role(self, db, role):
        with pytest.raises(ap.PRMSAccessDenied) as exc:
            _run(db, "SELECT value FROM global_parameters", role)
        assert exc.value.financial is False
        rows, _, _ = _run(db, "SELECT first_name, password, email FROM users", role)
        assert rows == [{"first_name": "Ada", "password": None, "email": None}]


# ---------------------------------------------------------------------------
# 4. The other entry points: prms_search filter_sql, scenario, partners
# ---------------------------------------------------------------------------

class TestOtherEntryPoints:

    def test_prms_search_filter_sql_refuses_budget_tables_for_external(self, db):
        def _call():
            with patch.object(ps, "PRMS_DB_PATH", str(db)):
                return ps._resolve_eligible(
                    "SELECT r.result_code FROM result r JOIN results_by_inititiative b ON b.result_id = r.id "
                    "JOIN result_initiative_budget g ON g.result_initiative_id = b.id WHERE g.current_year > 0",
                    None)
        eligible, err = _as("external", _call)
        assert eligible is None
        assert err and "not available in this external view" in err
        assert MONEY_TXT not in err
        eligible, err = _as("researcher", _call)
        assert err is None and eligible == {100}

    def test_prms_search_filter_sql_cannot_rank_by_a_blanked_column(self, db):
        def _call():
            with patch.object(ps, "PRMS_DB_PATH", str(db)):
                return ps._resolve_eligible(
                    "SELECT r.result_code FROM result r JOIN results_policy_changes p ON p.result_id = r.id "
                    "WHERE p.amount > 1000", None)
        assert _as("external", _call) == (set(), None)
        assert _as("researcher", _call) == ({102}, None)

    def test_prms_search_worker_thread_runs_with_the_callers_role(self):
        seen = {}

        def fake_run_search(args):
            seen["role"] = ap.caller_role()
            return success_response("ok")

        def _call():
            with patch.object(ps, "_run_search", fake_run_search):
                return asyncio.run(ps.prms_search.handler({"query": "maize"}))

        _as("external", _call)
        assert seen["role"] == "external"
        _as("researcher", _call)
        assert seen["role"] == "researcher"

    @pytest.mark.parametrize("module", [sa, pi])
    def test_helper_connections_carry_the_role_aware_policy(self, db, module):
        def _call():
            with patch.object(module, "PRMS_DB_PATH", str(db)):
                conn = module._get_connection()
            try:
                try:
                    conn.execute("SELECT COUNT(*) FROM result_initiative_budget").fetchall()
                    denied = False
                except sqlite3.DatabaseError:
                    denied = True
                nulled = conn.execute("SELECT total_budget FROM clarisa_projects WHERE id = 1").fetchone()[0]
                return denied, nulled
            finally:
                conn.close()
        assert _as("external", _call) == (True, None)
        assert _as("researcher", _call) == (False, MONEY)

    def test_scenario_assumption_wording_is_role_aware(self):
        ext = _as("external", sa._allocation_proxy_note)
        res = _as("researcher", sa._allocation_proxy_note)
        assert "financial figures are not part of this external view" in ext
        assert "5.6%" not in ext
        assert "budget data covers only 5.6% of results" in res


# ---------------------------------------------------------------------------
# 5. No other code path reads financial objects (fixed SQL, exports, index)
# ---------------------------------------------------------------------------

_FINANCIAL_IDENT = re.compile(
    r"result_initiative_budget|result_institutions_budget|non_pooled_projetct_budget|"
    r"total_budget|source_of_funding|allocation_percentage|program_invested_financial|"
    r"clarisa_project_mappings|clarisa_project_countries|\bin_cash\b|\bkind_cash\b",
    re.IGNORECASE,
)

#: Files allowed to name financial objects: the policy itself and the prompt
#: (which names a table only in its list of schema typos).
_ALLOWED = {"synapsis/prms_access_policy.py", "synapsis/system_prompt.py"}


def test_no_other_backend_module_reads_financial_objects():
    """Fixed-SQL readers (dashboard routes, search index corpus, citations,
    exports, documents, voice) open their own connections without the
    authorizer. They must never name a financial table or column, otherwise an
    external user could receive budget figures through them. The free-SQL
    tools are covered by the role-aware authorizer instead."""
    offenders = []
    for path in sorted((REPO / "synapsis").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel in _ALLOWED:
            continue
        if _FINANCIAL_IDENT.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(rel)
    assert offenders == []


def test_search_index_text_is_title_and_description_only():
    from synapsis.search import corpus

    sql = corpus._CANON_RESULT_SQL + corpus._CANON_BILATERAL_SQL
    assert not _FINANCIAL_IDENT.search(sql)
    selected = re.findall(r"SELECT(.*?)FROM", sql, flags=re.S | re.I)
    assert selected and all("budget" not in s.lower() for s in selected)


# ---------------------------------------------------------------------------
# 6. System prompt: external accounts are told to decline politely
# ---------------------------------------------------------------------------

class TestPrompt:

    def test_external_prompt_has_the_decline_rule(self):
        from synapsis.system_prompt import build_system_prompt

        prompt = build_system_prompt({}, role="external")
        assert "External view — budget and financial figures are not available" in prompt
        assert "isn't available in this external view" in prompt
        assert "Never describe it as missing" in prompt
        assert "investment amounts of policy-change results" in prompt
        assert "Scope of this view: the public Results Dashboard" not in prompt

    @pytest.mark.parametrize("role", [None, "admin", "researcher"])
    def test_full_access_prompt_is_unchanged(self, role):
        from synapsis.system_prompt import build_system_prompt

        prompt = build_system_prompt({}, role=role)
        assert "External view" not in prompt
        assert prompt == build_system_prompt({})

    def test_w12_only_toggle_adds_the_public_dashboard_scope(self, monkeypatch):
        from synapsis.system_prompt import build_system_prompt

        monkeypatch.setenv("IA_EXTERNAL_W12_ONLY", "true")
        assert "Scope of this view: the public Results Dashboard" in build_system_prompt({}, role="external")
        assert "Scope of this view" not in build_system_prompt({}, role="researcher")

    def test_factual_lead_in_replaces_prms_label(self):
        from synapsis.system_prompt import build_system_prompt

        prompt = build_system_prompt({})
        assert "**Factual — from CGIAR PRMS data (snapshot <date" in prompt
        assert "From the PRMS data (snapshot" not in prompt
        assert "**Interpretation:**" in prompt
        # PRMS stays in the citations / Sources list
        assert '"CGIAR PRMS Reporting, "' in prompt

    def test_agent_options_build_the_prompt_for_the_callers_role(self, monkeypatch):
        import synapsis.agent_options as ao

        seen = []
        monkeypatch.setattr(ao, "build_system_prompt", lambda agents, role=None: seen.append(role) or "p")

        async def _no_agents():
            return {}

        monkeypatch.setattr(ao, "load_all_agents", _no_agents)
        _as("external", lambda: asyncio.run(ao.build_agent_options()))
        _as("researcher", lambda: asyncio.run(ao.build_agent_options()))
        assert seen == ["external", "researcher"]


# ---------------------------------------------------------------------------
# 7. Real snapshot (skipped when the PRMS database is not available)
# ---------------------------------------------------------------------------

_REAL = pq.PRMS_DB_PATH if Path(pq.PRMS_DB_PATH).is_file() else None
real = pytest.mark.skipif(_REAL is None, reason="PRMS snapshot not available")


@real
class TestRealSnapshot:

    def test_every_blocked_object_exists_in_the_snapshot(self):
        conn = sqlite3.connect(f"file:{_REAL}?mode=ro", uri=True)
        try:
            for name in ap.blocked_financial_objects():
                table, _, column = name.partition(".")
                cols = {r[1] for r in conn.execute(f"SELECT * FROM pragma_table_info('{table}')")}
                assert cols, f"{table} missing from the snapshot"
                if column:
                    assert column in cols, f"{name} missing from the snapshot"
        finally:
            conn.close()

    def test_external_cannot_read_budget_figures(self):
        for table in ap.FINANCIAL_DENIED_TABLES:
            with pytest.raises(ap.PRMSAccessDenied):
                _run(Path(_REAL), f"SELECT COUNT(*) FROM {table}", "external")
        rows, _, _ = _run(Path(_REAL), "SELECT COUNT(*) AS n, COUNT(total_budget) AS b, "
                                       "COUNT(source_of_funding) AS f FROM clarisa_projects", "external")
        assert rows[0]["n"] > 0 and rows[0]["b"] == 0 and rows[0]["f"] == 0

    def test_researcher_still_reads_them(self):
        rows, _, _ = _run(Path(_REAL), "SELECT COUNT(total_budget) AS b FROM clarisa_projects", "researcher")
        assert rows[0]["b"] > 0

    def test_innovation_counts_are_identical_for_both_roles(self):
        sql = ("SELECT COUNT(DISTINCT result_code) AS n FROM result WHERE result_type_id = 7 "
               "AND is_active = 1 AND ((source='Result' AND status_id=2) OR (source='API' AND status_id=6))")
        ext, _, log = _run(Path(_REAL), sql, "external")
        res, _, _ = _run(Path(_REAL), sql, "researcher")
        assert ext == res and ext[0]["n"] > 0
        assert not log.denied and not log.nulled
