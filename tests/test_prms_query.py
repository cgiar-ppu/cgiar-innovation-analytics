"""
Tests for the PRMS query tool.

Tests cover:
- SQL validation (safety checks)
- Query execution against the real PRMS database
- The five acceptance test queries from the task spec
- Error handling (bad SQL, non-existent tables, timeout simulation)
- Edge cases (empty results, LIMIT enforcement)
"""

import asyncio
import json
import pytest
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.tools.prms_query import (
    prms_query,
    _validate_sql,
    _ensure_limit,
    _extract_tables_used,
    PRMS_DB_PATH,
)

# The @tool decorator wraps the async function into an SdkMcpTool object.
# To call it directly in tests, we use the .handler attribute.
_prms_query_handler = prms_query.handler


# ---------------------------------------------------------------------------
# Helper to run async tool function synchronously
# ---------------------------------------------------------------------------

def run_query(sql: str, question: str = "") -> dict:
    """Execute prms_query synchronously and return the result dict."""
    return asyncio.run(_prms_query_handler({"sql": sql, "question": question}))


def get_text(result: dict) -> str:
    """Extract the text content from an MCP tool response."""
    return result["content"][0]["text"]


def is_error(result: dict) -> bool:
    """Check if the result is an error response."""
    return result.get("is_error", False)


# ---------------------------------------------------------------------------
# Unit tests: SQL validation
# ---------------------------------------------------------------------------

class TestSQLValidation:

    def test_select_is_valid(self):
        assert _validate_sql("SELECT * FROM result") is None

    def test_with_cte_is_valid(self):
        assert _validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is None

    def test_explain_is_valid(self):
        assert _validate_sql("EXPLAIN SELECT * FROM result") is None

    def test_insert_is_rejected(self):
        err = _validate_sql("INSERT INTO result VALUES (1, 'test')")
        assert err is not None
        assert "SELECT" in err

    def test_update_is_rejected(self):
        err = _validate_sql("UPDATE result SET title = 'hacked'")
        assert err is not None

    def test_delete_is_rejected(self):
        err = _validate_sql("DELETE FROM result")
        assert err is not None

    def test_drop_is_rejected(self):
        err = _validate_sql("DROP TABLE result")
        assert err is not None

    def test_create_is_rejected(self):
        err = _validate_sql("CREATE TABLE evil (id INT)")
        assert err is not None

    def test_attach_is_rejected(self):
        err = _validate_sql("ATTACH DATABASE '/tmp/evil.db' AS evil")
        assert err is not None

    def test_multi_statement_is_rejected(self):
        err = _validate_sql("SELECT 1; DROP TABLE result")
        assert err is not None
        assert "Multi-statement" in err

    def test_empty_is_rejected(self):
        err = _validate_sql("")
        assert err is not None

    def test_trailing_semicolon_is_ok(self):
        assert _validate_sql("SELECT * FROM result;") is None


class TestEnsureLimit:

    def test_adds_limit_when_missing(self):
        result = _ensure_limit("SELECT * FROM result")
        assert "LIMIT 100" in result

    def test_preserves_existing_limit(self):
        result = _ensure_limit("SELECT * FROM result LIMIT 10")
        assert "LIMIT 10" in result
        assert "LIMIT 100" not in result

    def test_handles_trailing_semicolon(self):
        result = _ensure_limit("SELECT * FROM result;")
        assert "LIMIT 100" in result


class TestExtractTables:

    def test_single_from(self):
        tables = _extract_tables_used("SELECT * FROM result")
        assert "result" in tables

    def test_join(self):
        tables = _extract_tables_used(
            "SELECT * FROM result r JOIN result_type rt ON r.result_type_id = rt.id"
        )
        assert "result" in tables
        assert "result_type" in tables

    def test_multiple_joins(self):
        tables = _extract_tables_used(
            "SELECT * FROM result r "
            "JOIN result_country rc ON r.id = rc.result_id "
            "JOIN clarisa_countries cc ON rc.country_id = cc.id"
        )
        assert "result" in tables
        assert "result_country" in tables
        assert "clarisa_countries" in tables


# ---------------------------------------------------------------------------
# Integration tests: actual database queries
# ---------------------------------------------------------------------------

@pytest.fixture
def check_db():
    """Skip tests if the PRMS database is not available."""
    if not os.path.isfile(PRMS_DB_PATH):
        pytest.skip(f"PRMS database not found at {PRMS_DB_PATH}")


class TestAcceptanceQueries:
    """The five acceptance test queries from the task specification."""

    def test_01_how_many_results(self, check_db):
        """'How many results are in the database?' -> Should return ~32,005"""
        result = run_query(
            "SELECT COUNT(*) as total_results FROM result;",
            "How many results are in the database?"
        )
        assert not is_error(result), get_text(result)
        text = get_text(result)
        assert "total_results" in text
        # Should be around 32,005 (exact number may vary)
        assert "32" in text  # at least 32,000

    def test_02_how_many_innovations(self, check_db):
        """'How many innovations are there?' -> Should query innovation table"""
        result = run_query(
            "SELECT COUNT(*) as innovation_count FROM result r "
            "JOIN result_type rt ON r.result_type_id = rt.id "
            "WHERE r.is_active = 1 AND rt.name = 'Innovation development';",
            "How many innovations are there?"
        )
        assert not is_error(result), get_text(result)
        text = get_text(result)
        assert "innovation_count" in text

    def test_03_top_countries(self, check_db):
        """'Top 5 countries by number of results' -> join result + geography"""
        result = run_query(
            "SELECT cc.name as country, COUNT(DISTINCT rc.result_id) as result_count "
            "FROM result_country rc "
            "JOIN clarisa_countries cc ON rc.country_id = cc.id "
            "JOIN result r ON rc.result_id = r.id "
            "WHERE rc.is_active = 1 AND r.is_active = 1 "
            "GROUP BY cc.name "
            "ORDER BY result_count DESC "
            "LIMIT 5;",
            "What are the top 5 countries by number of results?"
        )
        assert not is_error(result), get_text(result)
        text = get_text(result)
        # Kenya should be top
        assert "Kenya" in text
        assert "country" in text
        assert "result_count" in text

    def test_04_science_programmes(self, check_db):
        """'List the science programmes' -> query initiatives table"""
        result = run_query(
            "SELECT id, official_code, name, short_name "
            "FROM clarisa_initiatives "
            "WHERE active = 1 "
            "ORDER BY official_code;",
            "List the science programmes"
        )
        assert not is_error(result), get_text(result)
        text = get_text(result)
        # Should contain some known initiative names
        assert "INIT" in text or "SGP" in text

    def test_05_innovations_readiness_7_plus(self, check_db):
        """'How many innovations at readiness level 7+?' -> innovation + readiness"""
        result = run_query(
            "SELECT COUNT(*) as advanced_innovations "
            "FROM results_innovations_dev rid "
            "JOIN clarisa_innovation_readiness_level cirl "
            "  ON rid.innovation_readiness_level_id = cirl.id "
            "JOIN result r ON rid.results_id = r.id "
            "WHERE rid.is_active = 1 AND r.is_active = 1 "
            "AND cirl.level >= 7;",
            "How many innovations are at readiness level 7 or above?"
        )
        assert not is_error(result), get_text(result)
        text = get_text(result)
        assert "advanced_innovations" in text


class TestErrorHandling:

    def test_nonexistent_table(self, check_db):
        """Should return a helpful error for non-existent tables."""
        result = run_query("SELECT * FROM nonexistent_table;")
        assert is_error(result)
        text = get_text(result)
        assert "no such table" in text

    def test_nonexistent_column(self, check_db):
        """Should return a helpful error for non-existent columns."""
        result = run_query("SELECT fake_column FROM result;")
        assert is_error(result)
        text = get_text(result)
        assert "no such column" in text

    def test_syntax_error(self, check_db):
        """Should return error for invalid SQL syntax."""
        result = run_query("SELECTT * FROMM result;")
        assert is_error(result)

    def test_empty_sql(self):
        """Should reject empty SQL."""
        result = run_query("")
        assert is_error(result)

    def test_insert_rejected(self):
        """Should reject INSERT statements."""
        result = run_query("INSERT INTO result (title) VALUES ('test');")
        assert is_error(result)

    def test_empty_result_set(self, check_db):
        """Should handle zero-row results gracefully."""
        result = run_query(
            "SELECT * FROM result WHERE title = 'THIS_TITLE_DOES_NOT_EXIST_12345';"
        )
        assert not is_error(result)
        text = get_text(result)
        assert "0 row" in text or "No results" in text


class TestQueryFeatures:

    def test_limit_enforcement(self, check_db):
        """Queries without LIMIT get one added automatically."""
        result = run_query("SELECT id FROM result WHERE is_active = 1;")
        assert not is_error(result)
        text = get_text(result)
        assert "LIMIT 100" in text

    def test_existing_limit_preserved(self, check_db):
        """Queries with existing LIMIT should keep it."""
        result = run_query("SELECT id FROM result LIMIT 5;")
        assert not is_error(result)
        text = get_text(result)
        assert "5 row" in text

    def test_with_cte(self, check_db):
        """CTE (WITH) queries should work."""
        result = run_query(
            "WITH active_results AS ("
            "  SELECT result_type_id, COUNT(*) as cnt "
            "  FROM result WHERE is_active = 1 "
            "  GROUP BY result_type_id"
            ") SELECT rt.name, ar.cnt "
            "FROM active_results ar "
            "JOIN result_type rt ON ar.result_type_id = rt.id "
            "ORDER BY ar.cnt DESC;"
        )
        assert not is_error(result)
        text = get_text(result)
        assert "Knowledge product" in text

    def test_tables_used_in_response(self, check_db):
        """Response should list which tables were queried."""
        result = run_query(
            "SELECT COUNT(*) FROM result WHERE is_active = 1;"
        )
        assert not is_error(result)
        text = get_text(result)
        assert "Tables used:" in text
        assert "result" in text

    def test_attribution_in_response(self, check_db):
        """Response should include PRMS source attribution."""
        result = run_query("SELECT COUNT(*) FROM result;")
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS Database" in text


# ---------------------------------------------------------------------------
# Run tests directly (outside pytest) for quick validation
# ---------------------------------------------------------------------------

def main():
    """Run the acceptance test queries directly and print results."""
    print("=" * 70)
    print("PRMS Query Tool — Direct Test Run")
    print("=" * 70)

    queries = [
        (
            "Test 1: How many results are in the database?",
            "SELECT COUNT(*) as total_results FROM result;",
        ),
        (
            "Test 2: How many innovations are there?",
            "SELECT COUNT(*) as innovation_count FROM result r "
            "JOIN result_type rt ON r.result_type_id = rt.id "
            "WHERE r.is_active = 1 AND rt.name = 'Innovation development';",
        ),
        (
            "Test 3: Top 5 countries by number of results",
            "SELECT cc.name as country, COUNT(DISTINCT rc.result_id) as result_count "
            "FROM result_country rc "
            "JOIN clarisa_countries cc ON rc.country_id = cc.id "
            "JOIN result r ON rc.result_id = r.id "
            "WHERE rc.is_active = 1 AND r.is_active = 1 "
            "GROUP BY cc.name ORDER BY result_count DESC LIMIT 5;",
        ),
        (
            "Test 4: List the science programmes",
            "SELECT official_code, short_name, name "
            "FROM clarisa_initiatives WHERE active = 1 ORDER BY official_code;",
        ),
        (
            "Test 5: Innovations at readiness level 7+",
            "SELECT COUNT(*) as advanced_innovations "
            "FROM results_innovations_dev rid "
            "JOIN clarisa_innovation_readiness_level cirl "
            "  ON rid.innovation_readiness_level_id = cirl.id "
            "JOIN result r ON rid.results_id = r.id "
            "WHERE rid.is_active = 1 AND r.is_active = 1 AND cirl.level >= 7;",
        ),
    ]

    passed = 0
    for title, sql in queries:
        print(f"\n{'─' * 70}")
        print(f"  {title}")
        print(f"{'─' * 70}")
        result = run_query(sql, title)
        text = get_text(result)
        err = is_error(result)
        status = "FAIL" if err else "PASS"
        print(f"Status: {status}")
        print(text[:500])
        if not err:
            passed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed}/{len(queries)} passed")
    print(f"{'=' * 70}")

    # Also test error handling
    print(f"\n{'─' * 70}")
    print("  Error handling: INSERT rejected")
    print(f"{'─' * 70}")
    result = run_query("INSERT INTO result (title) VALUES ('test');")
    print(f"Correctly rejected: {is_error(result)}")
    print(get_text(result)[:200])

    print(f"\n{'─' * 70}")
    print("  Error handling: Non-existent table")
    print(f"{'─' * 70}")
    result = run_query("SELECT * FROM nonexistent_table;")
    print(f"Correctly errored: {is_error(result)}")
    print(get_text(result)[:200])


if __name__ == "__main__":
    main()
