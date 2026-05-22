"""
Shared database helpers for route handlers.

Centralises repetitive patterns — fetch-or-404 and safe JSON parsing — so
individual route files stay focused on their domain logic.
"""

import json

from fastapi import HTTPException


async def fetch_one_or_404(db, query: str, params: tuple, entity_name: str):
    """Execute *query* with *params*, fetch one row, and raise HTTP 404 if missing.

    Args:
        db: An active aiosqlite connection (or compatible async DB handle).
        query: The SQL SELECT statement to execute.
        params: Positional parameters bound to the query.
        entity_name: Human-readable name used in the 404 detail message
            (e.g. ``"Workflow"`` or ``"Agent 'my_agent'"``)

    Returns:
        The fetched row (aiosqlite.Row).

    Raises:
        fastapi.HTTPException: 404 when no row is found.
    """
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, f"{entity_name} not found")
    return row


def safe_json_loads(value, default=None):
    """Decode a JSON string, returning *default* when the value is falsy.

    Args:
        value: The raw value to decode (typically a DB column).
        default: Fallback value when *value* is falsy. Defaults to ``[]``
            when ``None`` is passed so callers expecting a list work without
            an explicit default argument.

    Returns:
        Parsed Python object, or *default* (``[]`` if *default* is ``None``).
    """
    if value:
        return json.loads(value)
    return default if default is not None else []


async def dynamic_update(
    db,
    table: str,
    id_column: str,
    id_value,
    extra_sets: dict = None,
    **fields,
) -> None:
    """Generic dynamic SQL UPDATE with kwargs converted to SET clauses.

    Builds and executes an UPDATE statement of the form::

        UPDATE <table> SET col1 = ?, col2 = ? WHERE <id_column> = ?

    This eliminates the repeated pattern of manually assembling SET clauses
    and parameter lists that appears throughout the codebase.

    For compound WHERE clauses, pass *id_column* as a string like
    ``"run_id = ? AND step_index"`` and *id_value* as a tuple.

    Args:
        db:        An active aiosqlite connection (or compatible async DB).
        table:     The table name to update.
        id_column: The WHERE clause column name (e.g. ``"id"``).
                   For compound keys, pass the trailing column only and use
                   *extra_where* via the raw WHERE form below.
        id_value:  The value(s) for the WHERE clause.  Pass a tuple for
                   compound keys (see example below).
        extra_sets: Optional dict of additional column=value pairs to include.
                    Merged with **fields (fields take precedence).
        **fields:  Column name = value keyword arguments for the SET clause.

    Returns:
        None.  Does nothing (no-op) if no fields are provided.

    Examples::

        # Simple single-column WHERE
        await dynamic_update(db, "workflow_runs", "id", run_id,
                             status="completed", completed_at=time.time())

        # Compound WHERE: "WHERE run_id = ? AND step_index = ?"
        await dynamic_update(db, "workflow_run_steps",
                             "run_id = ? AND step_index", (run_id, step_index),
                             output_text="...", completed_at=time.time())
    """
    all_fields = {}
    if extra_sets:
        all_fields.update(extra_sets)
    all_fields.update(fields)

    if not all_fields:
        return

    set_clauses = ", ".join(f"{k} = ?" for k in all_fields)
    params = list(all_fields.values())

    # Support compound WHERE keys like "run_id = ? AND step_index"
    if isinstance(id_value, tuple):
        params.extend(id_value)
    else:
        params.append(id_value)

    await db.execute(
        f"UPDATE {table} SET {set_clauses} WHERE {id_column} = ?", params,
    )
    await db.commit()


def parse_json_field(record: dict, field: str) -> None:
    """Parse a JSON-encoded string field on *record* in place.

    If ``record[field]`` is a string, attempts ``json.loads``; on failure
    the original string value is left untouched.  This replaces the
    repetitive try/except pattern scattered across route handlers::

        if isinstance(record.get(field), str):
            try:
                record[field] = json.loads(record[field])
            except (json.JSONDecodeError, TypeError):
                pass

    Args:
        record: A mutable dict (e.g. a row dict from the database).
        field: The key whose value should be parsed.
    """
    value = record.get(field)
    if isinstance(value, str):
        try:
            record[field] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
