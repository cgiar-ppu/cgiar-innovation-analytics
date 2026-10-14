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
from synapsis.prms_snapshot import get_snapshot_info
from synapsis.prms_snapshot import resolve_db_path
from synapsis.prms_schema_check import is_expected_table, missing_table_message


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRMS_DB_PATH: str = resolve_db_path()  # env PRMS_DB_PATH, else coding/PRMSDB/current (auto-refreshed)

# Safety limits
# Default cap on rows returned when the query does not specify its own LIMIT
# and the caller does not pass an explicit row_limit. Raised from the previous
# value of 100 to 5000 so the agent can see full result sets; the cap still
# exists to guard against accidental runaway queries.
MAX_ROWS: int = 5000
# Hard ceiling on an explicit row_limit, to keep the safety guarantee even when
# the caller overrides the default.
MAX_ROW_LIMIT: int = 100000
QUERY_TIMEOUT_SECONDS: int = 30
# How often (in SQLite VM instructions) the progress handler checks the deadline,
# and how long the caller waits for the worker to unwind after an interrupt.
_PROGRESS_STEPS: int = 10_000
_INTERRUPT_GRACE_SECONDS: float = 5.0

# SQL patterns that are NOT allowed (anything other than SELECT)
_FORBIDDEN_SQL = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|REINDEX|PRAGMA\s+(?!query_only|table_info|database_list))",
    re.IGNORECASE | re.MULTILINE,
)

# Single-quoted SQL string literals ('' is an escaped quote inside one).
_SQL_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")

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
    # A ';' inside a string literal (e.g. GROUP_CONCAT(x, '; ')) is text, not a
    # statement separator. (sqlite3 also refuses to run two statements in one
    # execute() call, and the connection is read-only.)
    if ";" in _SQL_STRING_LITERAL.sub("''", core):
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
    """Execute a SQL query with a timeout that really stops SQLite.

    Returns (rows_as_dicts, column_names, total_row_count).
    Raises _TimeoutError if the query takes too long.
    Raises sqlite3.Error on SQL errors.

    L2-07 (2026-09-26): a timed-out query used to keep running in its daemon
    thread (the join simply stopped waiting), so one runaway recursive CTE could
    pin a CPU core of the backend until the process restarted. Two independent
    stops now end it:

    * a SQLite progress handler that aborts the statement once the deadline has
      passed (checked every ``_PROGRESS_STEPS`` VM instructions, in the worker
      thread itself), and
    * ``Connection.interrupt()`` called from the waiting thread when the join
      times out (belt and braces for statements that sit in a single long step).

    The connection is opened read-only (``mode=ro`` URI) and always closed.
    """
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Any] = {}
    conn_holder: dict[str, sqlite3.Connection] = {}
    deadline = time.monotonic() + timeout

    def _past_deadline() -> int:
        # Non-zero return value makes SQLite abort with "interrupted".
        return 1 if time.monotonic() > deadline else 0

    def _run():
        conn = None
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
                timeout=10,
                check_same_thread=False,
            )
            conn_holder["conn"] = conn
            conn.set_progress_handler(_past_deadline, _PROGRESS_STEPS)
            conn.execute("PRAGMA query_only = ON;")
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

            # Convert to list of dicts
            result_holder["rows"] = [dict(row) for row in rows]
            result_holder["columns"] = columns
            result_holder["count"] = len(rows)
        except Exception as exc:
            error_holder["error"] = exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # pragma: no cover - best effort
                    pass

    thread = threading.Thread(target=_run, name="prms-query", daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        conn = conn_holder.get("conn")
        if conn is not None:
            try:
                conn.interrupt()
            except Exception:  # pragma: no cover - connection already closed
                pass
        # Give SQLite a moment to unwind; the progress handler also fires.
        thread.join(timeout=_INTERRUPT_GRACE_SECONDS)
        raise _TimeoutError(
            f"Query timed out after {timeout} seconds and was stopped. "
            "Try simplifying the query or adding more specific WHERE conditions."
        )

    if "error" in error_holder:
        exc = error_holder["error"]
        if isinstance(exc, sqlite3.OperationalError) and "interrupt" in str(exc).lower():
            raise _TimeoutError(
                f"Query timed out after {timeout} seconds and was stopped. "
                "Try simplifying the query or adding more specific WHERE conditions."
            )
        raise exc

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


# QA-4 D5: PRMS titles were cut at 80 characters in the table view (73 % of
# result titles are longer), and the model "completed" them — once with an
# invented qualifier — while claiming the titles were as stored. Title/name
# columns now keep up to 250 characters (99 % of PRMS titles fit); anything
# still cut ends in "..." and the prompt says to keep that ellipsis.
_TITLE_COLUMN_RE = re.compile(r"(^|[_\s])(title|name)s?($|[_\s])", re.IGNORECASE)
TITLE_CELL_LIMIT = 250

# Base per-cell limits: table view (<= 12 columns) / key-value view (> 12).
TABLE_CELL_LIMIT = 80
KV_CELL_LIMIT = 200
# Marc Schut, 13 Oct 2026: every non-title cell was cut at 80 characters
# whatever the query, so the agent could not read the use numbers inside
# result descriptions (376-2,396 characters) — not even with SUBSTR() chunks,
# because each chunk was cut to 80 again. Long cells now share a fixed text
# budget: few long values (e.g. 18 descriptions) come back in full, many long
# values (e.g. 5,000 rows) still fall back to the base limit, so the extra
# output is bounded by LONG_TEXT_BUDGET characters (~12k tokens) per call.
LONG_TEXT_BUDGET = 48_000
MAX_CELL_LIMIT = 6_000
# Rows printed in key/value form (> 12 columns).
KV_MAX_ROWS = 20

_UNLIMITED = 10**12


def _cell_limit(column, default: int) -> int:
    return max(default, TITLE_CELL_LIMIT) if _TITLE_COLUMN_RE.search(str(column)) else default


def _water_level(lengths: list[int], budget: int) -> int:
    """Largest per-cell length T so that sum(min(len, T)) <= budget.

    Short values are kept whole; the remaining budget is shared equally by
    the longer ones. Returns ``_UNLIMITED`` when everything fits.
    """
    remaining = budget
    ordered = sorted(lengths)
    n = len(ordered)
    for i, length in enumerate(ordered):
        if length * (n - i) <= remaining:
            remaining -= length
            continue
        return max(remaining // (n - i), 0)
    return _UNLIMITED


def _cell_text(v) -> str:
    return str(v) if v is not None else "NULL"


def _long_text_limit(cells: list[tuple[str, str]], base: int) -> int:
    """Per-cell limit for the long cells of one output (never below *base*)."""
    long_lengths = [len(s) for col, s in cells if len(s) > _cell_limit(col, base)]
    if not long_lengths:
        return base
    level = _water_level(long_lengths, LONG_TEXT_BUDGET)
    return max(base, min(MAX_CELL_LIMIT, level))


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

    table_view = bool(columns) and len(columns) <= 12
    base = TABLE_CELL_LIMIT if table_view else KV_CELL_LIMIT
    shown_rows = rows if table_view else rows[:KV_MAX_ROWS]
    cells = [
        (str(k), _cell_text(v))
        for row in shown_rows
        for k, v in (((c, row.get(c, "")) for c in columns) if table_view else row.items())
    ]
    long_limit = _long_text_limit(cells, base)
    shortened = 0

    def _fit(column, s: str) -> str:
        nonlocal shortened
        limit = max(_cell_limit(column, base), long_limit)
        if len(s) > limit:
            shortened += 1
            return s[:limit - 3] + "..."
        return s

    if table_view:
        # Header row
        lines.append(" | ".join(str(c) for c in columns))
        lines.append(" | ".join("---" for _ in columns))
        for row in rows:
            lines.append(" | ".join(_fit(c, _cell_text(row.get(c, ""))) for c in columns))
    else:
        # Too many columns -- show as key-value blocks
        for i, row in enumerate(shown_rows):
            lines.append(f"--- Row {i + 1} ---")
            for k, v in row.items():
                lines.append(f"  {k}: {_fit(k, _cell_text(v))}")
            lines.append("")
        if row_count > len(shown_rows):
            lines.append(
                f"NOTE: only the first {len(shown_rows)} of {row_count} rows are printed "
                f"because the query returns {len(columns)} columns (more than 12). "
                "Select 12 columns or fewer to see every row as a table."
            )

    if shortened:
        lines.append("")
        lines.append(
            f"NOTE: {shortened} long text value(s) were shortened (they end in \"...\"; "
            f"cut at {long_limit} characters, titles/names at least {TITLE_CELL_LIMIT}). "
            "This is a display limit, not the stored text. Long values share a budget of "
            f"about {LONG_TEXT_BUDGET:,} characters per call (up to {MAX_CELL_LIMIT:,} per value): "
            "to read full text (e.g. result descriptions), query fewer rows or fewer long "
            "columns — about 15-20 full descriptions fit in one call — and never treat a "
            "shortened value as complete."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------

@tool(
    "prms_query",
    "Execute a read-only SQL query against the CGIAR PRMS database (a published "
    "PRMS Reporting snapshot with 200+ tables and 32K+ result rows covering "
    "innovations, knowledge products, capacity development, "
    "policy changes, partners, and geographies). "
    "Use the PRMS schema reference in your system prompt to construct valid SQL. "
    "Counting rules for innovations (result_type_id IN (2,7,10)): count COUNT(DISTINCT result_code), never rows or ids; "
    "apply the quality gate is_active=1 AND ((source='Result' AND status_id=2) OR (source='API' AND status_id=6)); "
    "exclude open reporting phases (see the system prompt) unless the user asks for provisional data; "
    "state the method and the snapshot date (printed in the 'Source:' footer) with every number. "
    "Returns structured results with row data, total count, and tables used. "
    "By default results are capped at 5000 rows; pass an integer 'row_limit' to "
    "raise or lower that cap when you need the full result set (or fewer rows). "
    "An explicit LIMIT clause in the SQL always takes precedence over row_limit. "
    "Long text: small result sets return text cells in full (a shared budget of about "
    "48,000 characters per call, up to 6,000 per value); large result sets shorten "
    "long cells (to 80 characters, titles/names 250), mark them with '...' and say so. "
    "To read full result descriptions, select only the rows you need (about 15-20 "
    "descriptions per call). If a query fails because an expected PRMS table is "
    "missing from the loaded snapshot, the tool says so: report it as a data-loading "
    "issue, never as proof that PRMS lacks the data.",
    {
        "sql": str,
        "question": str,
        "row_limit": int,
    },
)
async def prms_query(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a read-only SQL query against the PRMS database.

    Args (via tool schema):
        sql:       The SQL SELECT query to execute against the PRMS database (required).
        question:  The original natural language question being answered (optional,
                   for context/logging).
        row_limit: Optional integer overriding the default row cap (MAX_ROWS = 5000).
                   Use a larger value to retrieve full result sets, or a smaller value
                   to retrieve fewer rows. Values are clamped to the range
                   [1, MAX_ROW_LIMIT]. If the SQL already contains an explicit LIMIT
                   clause, that clause takes precedence and row_limit is ignored.

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

    # Resolve the effective row cap: explicit row_limit overrides the default,
    # clamped to a sane range to preserve the safety guarantee.
    effective_limit = MAX_ROWS
    raw_row_limit = args.get("row_limit")
    if raw_row_limit is not None:
        try:
            requested = int(raw_row_limit)
        except (TypeError, ValueError):
            return error_response(
                "Error: 'row_limit' must be an integer if provided."
            )
        if requested < 1:
            return error_response(
                "Error: 'row_limit' must be a positive integer."
            )
        effective_limit = min(requested, MAX_ROW_LIMIT)

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
    limited_sql = _ensure_limit(sql, effective_limit)

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
            table_match = re.search(r"no such table: (?:main\.)?(\w+)", err_msg)
            hint = ""
            if table_match and is_expected_table(table_match.group(1)):
                # Marc Schut, 13 Oct 2026: the table is documented and exists in
                # PRMS but was dropped by the snapshot load. Say so — the old
                # "might be named differently" hint sent the agent looking for
                # another source and it invented one.
                return error_response(
                    f"SQL error: {err_msg}. "
                    + missing_table_message(table_match.group(1))
                )
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

    # Get total count if we may have limited the results
    total_count = None
    if row_count >= effective_limit:
        total_count = _get_total_count(PRMS_DB_PATH, sql)

    # Format the response
    result_text = _format_results_text(rows, columns, total_count, limited_sql, tables_used)

    # Add metadata footer
    meta_lines = [
        "",
        "---",
        f"SQL executed: {limited_sql}",
        f"Execution time: {elapsed:.2f}s",
        f"Source: {get_snapshot_info(PRMS_DB_PATH).citation}",
    ]
    if question:
        meta_lines.insert(1, f"Question: {question}")

    return success_response(result_text + "\n".join(meta_lines))
