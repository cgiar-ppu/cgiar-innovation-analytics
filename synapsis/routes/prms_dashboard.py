"""
PRMS Dashboard API — live innovation analytics from the PRMS SQLite database.

- GET /api/dashboard/prms-stats  — Returns KPIs and chart data for the
  CGIAR Innovation Analytics dashboard, sourced from the read-only PRMS
  database.

All result counts use COUNT(DISTINCT result_code) to avoid duplicates.
Queries filter to innovation-related result types only:
  - Innovation use (result_type_id = 2)
  - Innovation development (result_type_id = 7)
  - Innovation Package (result_type_id = 10)

Data is cached in-memory for 5 minutes since the PRMS snapshot is static.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("synapsis.routes.prms_dashboard")

router = APIRouter(prefix="/api", tags=["prms-dashboard"])

# ---------------------------------------------------------------------------
# In-memory cache (module-level)
# ---------------------------------------------------------------------------
_cache: dict[str, Any] = {}
_cache_ts: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes

# ---------------------------------------------------------------------------
# PRMS database path
# ---------------------------------------------------------------------------
_PRMS_DB_PATH = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite",
)

# ---------------------------------------------------------------------------
# SQL Queries
# ---------------------------------------------------------------------------

_SQL_TOTAL_RESULTS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id IN (2, 7, 10);
"""

# Canonical innovation-development count: count by result_type_id on the
# result table (cross-type, distinct result_code), matching the
# results_by_type chart and the agent's verified counts. The previous
# results_innovations_dev join undercounted (1966 vs 2006) because not every
# innovation-development result has an active detail row in that table.
_SQL_TOTAL_INNOVATIONS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id = 7;
"""

# Canonical innovation-use count: count by result_type_id (type 2) on the
# result table. The previous results_innovations_use join undercounted
# (488 vs 669) for the same reason as above.
_SQL_INNOVATION_USES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id = 2;
"""

_SQL_ACTIVE_INITIATIVES = """
SELECT COUNT(DISTINCT i.id)
FROM clarisa_initiatives i
JOIN results_by_inititiative rbi ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1 AND r.result_type_id IN (2, 7, 10);
"""

_SQL_COUNTRIES_COVERED = """
SELECT COUNT(DISTINCT rc.country_id)
FROM result_country rc
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1 AND r.result_type_id IN (2, 7, 10);
"""

_SQL_INNOVATION_PACKAGES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id = 10;
"""

_SQL_RESULTS_BY_TYPE = """
SELECT rt.name AS type, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN result_type rt ON r.result_type_id = rt.id
WHERE r.is_active = 1 AND r.result_type_id IN (2, 7, 10)
GROUP BY rt.name
ORDER BY count DESC;
"""

_SQL_TOP_COUNTRIES = """
SELECT c.name AS country, COUNT(DISTINCT r.result_code) AS count
FROM result_country rc
JOIN clarisa_countries c ON rc.country_id = c.id
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1 AND r.result_type_id IN (2, 7, 10)
GROUP BY c.name
ORDER BY count DESC
LIMIT 10;
"""

_SQL_IRL_DISTRIBUTION = """
SELECT cirl.name AS level, COUNT(DISTINCT r.result_code) AS count
FROM results_innovations_dev rid
JOIN result r ON r.id = rid.results_id
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
WHERE rid.is_active = 1 AND r.is_active = 1
GROUP BY cirl.name, cirl.id
ORDER BY cirl.id;
"""

_SQL_TOP_INITIATIVES = """
SELECT i.short_name AS initiative, COUNT(DISTINCT r.result_code) AS count
FROM results_by_inititiative rbi
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1 AND rbi.initiative_role_id = 1 AND r.result_type_id IN (2, 7, 10)
GROUP BY i.short_name
ORDER BY count DESC
LIMIT 10;
"""


# ---------------------------------------------------------------------------
# Helper: run a scalar query and return the single integer value
# ---------------------------------------------------------------------------
def _scalar(cursor: sqlite3.Cursor, sql: str) -> int:
    """Execute a query and return the first column of the first row as int."""
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Helper: run a query and return all rows as list of dicts
# ---------------------------------------------------------------------------
def _rows(cursor: sqlite3.Cursor, sql: str) -> list[dict[str, Any]]:
    """Execute a query and return all rows as a list of dicts."""
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Core: fetch all dashboard data from the PRMS database
# ---------------------------------------------------------------------------
def _fetch_prms_data() -> dict[str, Any]:
    """Connect to the PRMS SQLite database and run all dashboard queries.

    Returns the full API response dict. Raises FileNotFoundError if the
    database file does not exist, and sqlite3.Error on query failures.
    """
    if not os.path.isfile(_PRMS_DB_PATH):
        raise FileNotFoundError(f"PRMS database not found at: {_PRMS_DB_PATH}")

    conn = sqlite3.connect(f"file:{_PRMS_DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.cursor()

        # -- KPIs (each wrapped individually so partial results are possible) --
        kpis: dict[str, int] = {}
        kpi_queries = {
            "total_results": _SQL_TOTAL_RESULTS,
            "total_innovations": _SQL_TOTAL_INNOVATIONS,
            "innovation_uses": _SQL_INNOVATION_USES,
            "active_initiatives": _SQL_ACTIVE_INITIATIVES,
            "countries_covered": _SQL_COUNTRIES_COVERED,
            "innovation_packages": _SQL_INNOVATION_PACKAGES,
        }
        for key, sql in kpi_queries.items():
            try:
                kpis[key] = _scalar(cur, sql)
            except sqlite3.Error as exc:
                logger.error("KPI query '%s' failed: %s", key, exc)
                kpis[key] = 0

        # -- Charts --
        charts: dict[str, Any] = {}

        # Innovations by type (pie chart)
        try:
            results_by_type_data = _rows(cur, _SQL_RESULTS_BY_TYPE)
            # Note: summing per-type counts double-counts results that carry
            # more than one innovation type, so it does not equal the distinct
            # total_results (2755). Keep the description generic rather than
            # baking in a potentially misleading snapshot number.
            charts["results_by_type"] = {
                "chartType": "pie",
                "title": "Innovations by Type",
                "description": "Distribution of innovation results across types",
                "xAxisKey": "type",
                "data": results_by_type_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#427730"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'results_by_type' failed: %s", exc)

        # Top 10 countries (bar chart)
        try:
            top_countries_data = _rows(cur, _SQL_TOP_COUNTRIES)
            charts["top_countries"] = {
                "chartType": "bar",
                "title": "Top 10 Countries by Innovations",
                "description": "Countries with the most reported innovation results",
                "xAxisKey": "country",
                "data": top_countries_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#0065BD"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'top_countries' failed: %s", exc)

        # IRL distribution (bar chart)
        try:
            irl_data = _rows(cur, _SQL_IRL_DISTRIBUTION)
            charts["irl_distribution"] = {
                "chartType": "bar",
                "title": "Innovation Readiness Levels",
                "description": "Distribution of innovations across IRL 0-9 scale",
                "xAxisKey": "level",
                "data": irl_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#7AB800"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'irl_distribution' failed: %s", exc)

        # Top 10 initiatives (bar chart)
        try:
            top_initiatives_data = _rows(cur, _SQL_TOP_INITIATIVES)
            charts["top_initiatives"] = {
                "chartType": "bar",
                "title": "Top 10 Initiatives by Innovations",
                "description": "CGIAR initiatives contributing the most innovations",
                "xAxisKey": "initiative",
                "data": top_initiatives_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#E37222"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'top_initiatives' failed: %s", exc)

        return {
            "kpis": kpis,
            "charts": charts,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/dashboard/prms-stats")
async def prms_dashboard_stats():
    """Return PRMS dashboard KPIs and chart data.

    Results are cached in-memory for 5 minutes. If the PRMS database is
    unavailable a 503 is returned. Partial data is returned when individual
    queries fail.
    """
    global _cache, _cache_ts

    # Return cached data if still fresh
    now = time.monotonic()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    # Fetch fresh data
    try:
        data = _fetch_prms_data()
    except FileNotFoundError as exc:
        logger.error("PRMS database unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": "PRMS database unavailable",
                "detail": str(exc),
            },
        )
    except sqlite3.Error as exc:
        logger.error("PRMS database error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": "PRMS database error",
                "detail": str(exc),
            },
        )

    # Update cache
    _cache = data
    _cache_ts = now

    return data
