"""
db_init.py — SQLite index initialization for PRMS database.

Runs CREATE INDEX IF NOT EXISTS for all analytical indexes at app startup.
This is safe to call repeatedly and survives DB refresh (new SQLite artifacts
arrive without indexes; this function recreates them automatically).

One-time cost: ~27ms total for all 5 indexes on a 32K-row table.
"""

import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

# Indexes that must exist on the `result` table for acceptable query performance.
# Every analytical query filters or groups on these columns.
# Without these, every query is a full 32K-row scan.
RESULT_TABLE_INDEXES = [
    {
        "name": "idx_result_type_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_result_type_id ON result (result_type_id)",
        "description": "Innovation type filter (2=IU, 7=ID, 10=IP)",
    },
    {
        "name": "idx_result_is_discontinued",
        "sql": "CREATE INDEX IF NOT EXISTS idx_result_is_discontinued ON result (is_discontinued)",
        "description": "Discontinued exclusion filter",
    },
    {
        "name": "idx_result_is_active",
        "sql": "CREATE INDEX IF NOT EXISTS idx_result_is_active ON result (is_active)",
        "description": "Active record baseline filter",
    },
    {
        "name": "idx_result_result_code",
        "sql": "CREATE INDEX IF NOT EXISTS idx_result_result_code ON result (result_code)",
        "description": "COUNT(DISTINCT result_code) and latest-year dedup joins",
    },
    {
        "name": "idx_result_reported_year_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_result_reported_year_id ON result (reported_year_id)",
        "description": "MAX(reported_year_id) GROUP BY result_code dedup subqueries",
    },
]


def ensure_result_indexes(db_path: str) -> None:
    """
    Create all analytical indexes on the `result` table if they don't exist.

    Safe to call at every startup — IF NOT EXISTS makes it a no-op when indexes
    are already present. Logs a summary of what was done.

    This function intentionally never raises: index creation is a performance
    optimization, not a correctness requirement, so a failure here (e.g. a
    read-only filesystem or a missing DB file) must not block app startup. Any
    error is logged and swallowed.
    """
    t_start = time.perf_counter()

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        logger.warning(
            "db_init: could not open DB at %s for index creation: %s", db_path, exc
        )
        return

    try:
        # Check which indexes already exist
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='result'"
            ).fetchall()
        }

        created = []
        skipped = []

        for idx in RESULT_TABLE_INDEXES:
            conn.execute(idx["sql"])
            if idx["name"] in existing:
                skipped.append(idx["name"])
            else:
                created.append(idx["name"])

        conn.commit()
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        if created:
            logger.info(
                f"db_init: Created {len(created)} new index(es) on 'result' table "
                f"in {elapsed_ms:.0f}ms: {created}"
            )
        if skipped:
            logger.debug(
                f"db_init: {len(skipped)} index(es) already present (no-op): {skipped}"
            )
        if not created and not skipped:
            logger.info("db_init: result table indexes verified (all present)")

    except sqlite3.Error as exc:
        # Most likely cause: DB shipped read-only, or 'result' table absent in a
        # malformed artifact. Log and continue — queries still work, just slower.
        logger.warning("db_init: index creation failed (continuing without): %s", exc)
    finally:
        conn.close()
