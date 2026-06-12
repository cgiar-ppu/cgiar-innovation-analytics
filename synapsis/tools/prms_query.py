"""
PRMS query MCP tool -- executes read-only SQL against the PRMS SQLite database.

The orchestrator agent has the PRMS schema reference in its system prompt and
generates SQL queries. This tool accepts SQL, validates it for safety, executes
it against the database, and returns structured results with metadata.

The tool also accepts a natural language question alongside the SQL so the
agent can record what the query was answering.
"""

import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRMS_DB_PATH: str = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite",
)

# Safety limits
MAX_ROWS: int = 100
QUERY_TIMEOUT_SECONDS: int = 30

# SQL patterns that are NOT allowed (anything other than SELECT)
_FORBIDDEN_SQL = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|REINDEX|PRAGMA\s+(?!query_only|table_info|database_list))",
    re.IGNORECASE | re.MULTILINE,
)

# Detect if a LIMIT clause is already present (simple heuristic)
_HAS_LIMIT = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_sql(sql: str) -> str | None:
    """Validate that the SQL is a safe read-only query.

    Returns None if valid, or an error message string if invalid.
    """
    stripped = sql.strip()
    if not stripped:
        return "Empty SQL query."

    # Must start with SELECT, WITH, or EXPLAIN
    if not re.match(r"^\s*(SELECT|WITH|EXPLAIN)\b", stripped, re.IGNORECASE):
        return (
            "Only SELECT queries are allowed. "
            "The query must start with SELECT, WITH, or EXPLAIN."
        )

    # Check for forbidden statements (could be embedded in CTEs, etc.)
    if _FORBIDDEN_SQL.search(stripped):
        return (
            "Query contains a forbidden statement (INSERT, UPDATE, DELETE, DROP, "
            "ALTER, CREATE, ATTACH, or DETACH). Only read-only queries are allowed."
        )

    # Reject semicolons in the middle (potential multi-statement injection)
    # Allow trailing semicolon
    core = stripped.rstrip(";").strip()
    if ";" in core:
        return (
            "Multi-statement queries are not allowed. "
            "Please send a single SELECT statement."
        )

    return None


def _ensure_limit(sql: str, limit: int = MAX_ROWS) -> str:
    """Add a LIMIT clause if one is not already present."""
    if _HAS_LIMIT.search(sql):
        return sql
    # Strip trailing semicolon, add LIMIT, re-add semicolon
    stripped = sql.rstrip().rstrip(";").rstrip()
    return f"{stripped} LIMIT {limit};"


def _extract_tables_used(sql: str) -> list[str]:
    """Extract table names referenced in the SQL (best-effort heuristic)."""
    # Match FROM <table> and JOIN <table> patterns
    tables: set[str] = set()
    # FROM and JOIN patterns (handles backticks and brackets)
    for match in re.finditer(
        r"(?:FROM|JOIN)\s+[`\[]?(\w+)[`\]]?", sql, re.IGNORECASE
    ):
        tables.add(match.group(1))
    return sorted(tables)


class _TimeoutError(Exception):
    """Raised when a query exceeds the timeout."""


def _execute_with_timeout(
    db_path: str, sql: str, timeout: int = QUERY_TIMEOUT_SECONDS
) -> tuple[list[dict], list[str], int]:
    """Execute a SQL query with a timeout.

    Returns (rows_as_dicts, column_names, total_row_count).
    Raises _TimeoutError if the query takes too long.
    Raises sqlite3.Error on SQL errors.
    """
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Any] = {}

    def _run():
        try:
            conn = sqlite3.connect(
                db_path,
                timeout=10,
                check_same_thread=False,
            )
            conn.execute("PRAGMA query_only = ON;")
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

            # Convert to list of dicts
            result_holder["rows"] = [dict(row) for row in rows]
            result_holder["columns"] = columns
            result_holder["count"] = len(rows)

            conn.close()
        except Exception as exc:
            error_holder["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise _TimeoutError(
            f"Query timed out after {timeout} seconds. "
            "Try simplifying the query or adding more specific WHERE conditions."
        )

    if "error" in error_holder:
        raise error_holder["error"]

    return (
        result_holder.get("rows", []),
        result_holder.get("columns", []),
        result_holder.get("count", 0),
    )


def _get_total_count(db_path: str, sql: str) -> int | None:
    """Attempt to get the total row count for a query (before LIMIT).

    Returns None if it cannot be determined (e.g., query too complex).
    """
    # Strip existing LIMIT
    count_sql = re.sub(r"\bLIMIT\s+\d+\s*(OFFSET\s+\d+)?", "", sql, flags=re.IGNORECASE)
    count_sql = count_sql.rstrip().rstrip(";").rstrip()
    count_sql = f"SELECT COUNT(*) as total FROM ({count_sql})"

    try:
        rows, _, _ = _execute_with_timeout(db_path, count_sql, timeout=15)
        if rows:
            return rows[0].get("total", None)
    except Exception:
        pass
    return None


def _format_results_text(
    rows: list[dict],
    columns: list[str],
    total_count: int | None,
    sql: str,
    tables_used: list[str],
) -> str:
    """Format query results as readable text for the agent."""
    lines: list[str] = []

    # Header
    row_count = len(rows)
    if total_count is not None and total_count > row_count:
        lines.append(f"Query returned {row_count} rows (of {total_count} total).")
    else:
        lines.append(f"Query returned {row_count} row{'s' if row_count != 1 else ''}.")

    lines.append(f"Tables used: {', '.join(tables_used) if tables_used else 'unknown'}")
    lines.append("")

    if not rows:
        lines.append("No results found.")
        return "\n".join(lines)

    # Format as a table if reasonable number of columns
    if columns and len(columns) <= 12:
        # Header row
        lines.append(" | ".join(str(c) for c in columns))
        lines.append(" | ".join("---" for _ in columns))

        for row in rows:
            vals = []
            for c in columns:
                v = row.get(c, "")
                s = str(v) if v is not None else "NULL"
                # Truncate long values
                if len(s) > 80:
                    s = s[:77] + "..."
                vals.append(s)
            lines.append(" | ".join(vals))
    else:
        # Too many columns -- show as key-value blocks
        for i, row in enumerate(rows[:20]):
            lines.append(f"--- Row {i + 1} ---")
            for k, v in row.items():
                s = str(v) if v is not None else "NULL"
                if len(s) > 200:
                    s = s[:197] + "..."
                lines.append(f"  {k}: {s}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------

@tool(
    "prms_query",
    "Execute a read-only SQL query against the CGIAR PRMS database (197 tables, "
    "32K+ results covering innovations, knowledge products, capacity development, "
    "policy changes, partners, and geographies). "
    "Use the PRMS schema reference in your system prompt to construct valid SQL. "
    "For innovations (result_type_id IN (2,7,10)): always filter is_active=1 AND (is_discontinued IS NULL OR is_discontinued=0). Count by result_code not id. "
    "Returns structured results with row data, total count, and tables used.",
    {
        "sql": str,
        "question": str,
    },
)
async def prms_query(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a read-only SQL query against the PRMS database.

    Args (via tool schema):
        sql:      The SQL SELECT query to execute against the PRMS database (required).
        question: The original natural language question being answered (optional,
                  for context/logging).

    Returns:
        MCP-formatted response with query results, metadata, and attribution.
    """
    sql = args.get("sql", "").strip()
    question = args.get("question", "").strip()

    if not sql:
        return error_response(
            "Error: 'sql' parameter is required. Provide a SELECT query to execute "
            "against the PRMS database."
        )

    # Validate the SQL
    validation_error = _validate_sql(sql)
    if validation_error:
        return error_response(f"SQL validation error: {validation_error}")

    # Check database exists
    if not Path(PRMS_DB_PATH).is_file():
        return error_response(
            f"PRMS database not found at {PRMS_DB_PATH}. "
            "Set the PRMS_DB_PATH environment variable to the correct path."
        )

    # Ensure LIMIT is present
    limited_sql = _ensure_limit(sql, MAX_ROWS)

    # Extract tables for attribution
    tables_used = _extract_tables_used(limited_sql)

    # Execute
    start_time = time.monotonic()
    try:
        rows, columns, row_count = _execute_with_timeout(
            PRMS_DB_PATH, limited_sql, QUERY_TIMEOUT_SECONDS
        )
    except _TimeoutError as exc:
        return error_response(str(exc))
    except sqlite3.OperationalError as exc:
        err_msg = str(exc)
        # Provide helpful hints for common errors
        if "no such table" in err_msg:
            table_match = re.search(r"no such table: (\w+)", err_msg)
            hint = ""
            if table_match:
                bad_table = table_match.group(1)
                hint = (
                    f" Check the schema reference -- the table might be named "
                    f"differently. Common confusions: 'initiatives' vs "
                    f"'clarisa_initiatives', 'countries' vs 'clarisa_countries', "
                    f"'results_by_inititiative' (note the typo in the table name)."
                )
            return error_response(f"SQL error: {err_msg}.{hint}")
        if "no such column" in err_msg:
            return error_response(
                f"SQL error: {err_msg}. Check column names in the schema reference. "
                f"Common gotchas: 'results_id' (with 's') in innovation tables, "
                f"'inititiative_id' (extra 'i') in results_by_inititiative, "
                f"'institutionId' (camelCase) in clarisa_center."
            )
        return error_response(f"SQL error: {err_msg}")
    except sqlite3.Error as exc:
        return error_response(f"Database error: {exc}")
    except Exception as exc:
        return error_response(f"Unexpected error executing query: {exc}")

    elapsed = time.monotonic() - start_time

    # Get total count if we limited the results
    total_count = None
    if row_count >= MAX_ROWS:
        total_count = _get_total_count(PRMS_DB_PATH, sql)

    # Format the response
    result_text = _format_results_text(rows, columns, total_count, limited_sql, tables_used)

    # Add metadata footer
    meta_lines = [
        "",
        "---",
        f"SQL executed: {limited_sql}",
        f"Execution time: {elapsed:.2f}s",
        f"Source: PRMS Database (snapshot 2026-03-18)",
    ]
    if question:
        meta_lines.insert(1, f"Question: {question}")

    return success_response(result_text + "\n".join(meta_lines))
