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
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("synapsis.routes.prms_dashboard")

router = APIRouter(prefix="/api", tags=["prms-dashboard"])

# Years the year filter accepts. "All years" is represented by year=None.
_VALID_YEARS = {2022, 2023, 2024, 2025}

# ---------------------------------------------------------------------------
# In-memory cache (module-level) — keyed by year so each slice caches separately
# ---------------------------------------------------------------------------
_cache: dict[Any, dict[str, Any]] = {}
_cache_ts: dict[Any, float] = {}
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
# Year-scoped queries
# ---------------------------------------------------------------------------
# When a specific year is requested, the dashboard is sliced to that reporting
# year. We anchor the Innovation Development slice to the CANONICAL latest-phase
# dedup (matching the official annual totals 2022=62, 2023=160, 2024=445,
# 2025=1,185 for W1/W2 'Result' source), so the headline KPI is dashboard-
# aligned rather than the inflated "alive-in-year" count.
#
# _CANON_YEAR_IDS_CTE produces canon_year_ids(result_id) — the set of result.id
# rows that are the canonical latest-phase row for a result_code whose canonical
# year == :year. Downstream KPI/chart queries JOIN against it so every breakdown
# is consistent with the headline number. :year is bound twice via named params.
_CANON_YEAR_IDS_CTE = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
-- Candidate set spans ALL result types (no type filter here). Filtering to
-- type 7 BEFORE the latest-phase dedup is WRONG: it keeps a stale earlier
-- phase as "latest" for codes whose newest phase is a different type, which
-- inflated 2022/2023 to 83/172. Dedup across all types first, then filter
-- result_type_id = 7 at the very end (in canon_year_ids). This yields the
-- canonical W1/W2 counts 2022=62, 2023=160, 2024=445, 2025=963.
cand AS (
    SELECT r.result_code, r.reported_year_id, r.id, r.result_type_id, o.o AS phord
    FROM result r JOIN ord o ON o.v = r.version_id
    WHERE r.source = 'Result'
      AND r.is_active = 1 AND r.status_id = 2
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (
    SELECT c.* FROM cand c
    JOIN pick p ON p.result_code = c.result_code AND p.m = c.phord
),
canon AS (
    SELECT l.* FROM latest l
    WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code)
),
canon_year_ids AS (
    SELECT id AS result_id, result_code FROM canon
    WHERE result_type_id = 7 AND reported_year_id = :year
)
"""

# Bilateral (W3/API) Innovation Developments for the requested year — added to
# the headline count so it matches the canonical "include W3/bilateral" totals.
_SQL_YEAR_BILATERAL = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7 AND source = 'API' AND status_id = 6
  AND is_active = 1 AND reported_year_id = :year;
"""

# Headline Innovation Developments KPI for the year (W1/W2 canonical count).
_SQL_YEAR_INNOVATIONS = _CANON_YEAR_IDS_CTE + """
SELECT COUNT(*) FROM canon_year_ids;
"""

# Innovation Use (type 2) and Innovation Package (type 10) for the year use the
# dashboard filter scoped by reported_year_id. These types do not carry the same
# multi-year phase-chain dedup concern at the dashboard's granularity, so a
# direct reported_year_id slice is acceptable and clearly year-labelled in the UI.
_SQL_YEAR_USES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND source = 'Result' AND status_id = 2
  AND result_type_id = 2 AND reported_year_id = :year;
"""

_SQL_YEAR_PACKAGES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND source = 'Result' AND status_id = 2
  AND result_type_id = 10 AND reported_year_id = :year;
"""

# Total results KPI for the year (all three innovation types, dashboard filter).
_SQL_YEAR_TOTAL_RESULTS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND source = 'Result' AND status_id = 2
  AND result_type_id IN (2, 7, 10) AND reported_year_id = :year;
"""

_SQL_YEAR_INITIATIVES = """
SELECT COUNT(DISTINCT i.id)
FROM clarisa_initiatives i
JOIN results_by_inititiative rbi ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1 AND r.source = 'Result' AND r.status_id = 2
  AND r.result_type_id IN (2, 7, 10) AND r.reported_year_id = :year;
"""

_SQL_YEAR_COUNTRIES = """
SELECT COUNT(DISTINCT rc.country_id)
FROM result_country rc
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1 AND r.source = 'Result'
  AND r.status_id = 2 AND r.result_type_id IN (2, 7, 10)
  AND r.reported_year_id = :year;
"""

# Charts scoped to the canonical Innovation Development slice for the year.
_SQL_YEAR_TOP_COUNTRIES = _CANON_YEAR_IDS_CTE + """
SELECT c.name AS country, COUNT(DISTINCT cyi.result_code) AS count
FROM canon_year_ids cyi
JOIN result_country rc ON rc.result_id = cyi.result_id AND rc.is_active = 1
JOIN clarisa_countries c ON rc.country_id = c.id
GROUP BY c.name
ORDER BY count DESC
LIMIT 10;
"""

_SQL_YEAR_IRL_DISTRIBUTION = _CANON_YEAR_IDS_CTE + """
SELECT cirl.name AS level, COUNT(DISTINCT cyi.result_code) AS count
FROM canon_year_ids cyi
JOIN results_innovations_dev rid ON rid.results_id = cyi.result_id AND rid.is_active = 1
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
GROUP BY cirl.name, cirl.id
ORDER BY cirl.id;
"""

_SQL_YEAR_TOP_INITIATIVES = _CANON_YEAR_IDS_CTE + """
SELECT i.short_name AS initiative, COUNT(DISTINCT cyi.result_code) AS count
FROM canon_year_ids cyi
JOIN results_by_inititiative rbi ON rbi.result_id = cyi.result_id AND rbi.initiative_role_id = 1
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
GROUP BY i.short_name
ORDER BY count DESC
LIMIT 10;
"""

# Results-by-type for a year: each innovation type counted with the dashboard
# filter scoped to the reporting year. (type 7 uses the canonical W1/W2 count.)
_SQL_YEAR_RESULTS_BY_TYPE = _CANON_YEAR_IDS_CTE + """
SELECT 'Innovation Development' AS type, (SELECT COUNT(*) FROM canon_year_ids) AS count
UNION ALL
SELECT 'Innovation Use' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1 AND source = 'Result' AND status_id = 2
      AND result_type_id = 2 AND reported_year_id = :year)
UNION ALL
SELECT 'Innovation Package' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1 AND source = 'Result' AND status_id = 2
      AND result_type_id = 10 AND reported_year_id = :year);
"""


# ---------------------------------------------------------------------------
# Helper: run a scalar query and return the single integer value
# ---------------------------------------------------------------------------
def _scalar(cursor: sqlite3.Cursor, sql: str, params: dict | None = None) -> int:
    """Execute a query and return the first column of the first row as int."""
    cursor.execute(sql, params or {})
    row = cursor.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Helper: run a query and return all rows as list of dicts
# ---------------------------------------------------------------------------
def _rows(cursor: sqlite3.Cursor, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Execute a query and return all rows as a list of dicts."""
    cursor.execute(sql, params or {})
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Core: fetch all dashboard data from the PRMS database
# ---------------------------------------------------------------------------
def _fetch_prms_data(year: Optional[int] = None) -> dict[str, Any]:
    """Connect to the PRMS SQLite database and run all dashboard queries.

    Args:
        year: If provided (2022-2025), the dashboard is sliced to that reporting
            year — Innovation Development KPIs and charts use the canonical
            latest-phase dedup so the headline matches the official annual
            totals. If None, returns the all-years portfolio view (unchanged).

    Returns the full API response dict. Raises FileNotFoundError if the
    database file does not exist, and sqlite3.Error on query failures.
    """
    if not os.path.isfile(_PRMS_DB_PATH):
        raise FileNotFoundError(f"PRMS database not found at: {_PRMS_DB_PATH}")

    is_year = year is not None
    params = {"year": year} if is_year else None
    label_suffix = f" ({year})" if is_year else ""

    conn = sqlite3.connect(f"file:{_PRMS_DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.cursor()

        # -- KPIs (each wrapped individually so partial results are possible) --
        kpis: dict[str, int] = {}
        if is_year:
            kpi_queries = {
                "total_results": _SQL_YEAR_TOTAL_RESULTS,
                "total_innovations": _SQL_YEAR_INNOVATIONS,
                "innovation_uses": _SQL_YEAR_USES,
                "active_initiatives": _SQL_YEAR_INITIATIVES,
                "countries_covered": _SQL_YEAR_COUNTRIES,
                "innovation_packages": _SQL_YEAR_PACKAGES,
            }
        else:
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
                kpis[key] = _scalar(cur, sql, params)
            except sqlite3.Error as exc:
                logger.error("KPI query '%s' failed: %s", key, exc)
                kpis[key] = 0

        # When filtering to a single year, the canonical Innovation Development
        # KPI counts W1/W2 only. Add the W3/bilateral (API) count so the headline
        # matches the official "include bilateral" annual totals (e.g. 2025 =
        # 963 W1/W2 + 222 bilateral = 1,185).
        if is_year:
            try:
                kpis["total_innovations"] += _scalar(cur, _SQL_YEAR_BILATERAL, params)
            except sqlite3.Error as exc:
                logger.error("KPI query 'year_bilateral' failed: %s", exc)

        # -- Charts --
        charts: dict[str, Any] = {}
        sql_results_by_type = _SQL_YEAR_RESULTS_BY_TYPE if is_year else _SQL_RESULTS_BY_TYPE
        sql_top_countries = _SQL_YEAR_TOP_COUNTRIES if is_year else _SQL_TOP_COUNTRIES
        sql_irl = _SQL_YEAR_IRL_DISTRIBUTION if is_year else _SQL_IRL_DISTRIBUTION
        sql_top_initiatives = _SQL_YEAR_TOP_INITIATIVES if is_year else _SQL_TOP_INITIATIVES

        # Innovations by type (pie chart)
        try:
            results_by_type_data = _rows(cur, sql_results_by_type, params)
            # Note: summing per-type counts double-counts results that carry
            # more than one innovation type, so it does not equal the distinct
            # total_results. Keep the description generic rather than baking in
            # a potentially misleading snapshot number.
            charts["results_by_type"] = {
                "chartType": "pie",
                "title": f"Innovations by Type{label_suffix}",
                "description": "Distribution of innovation results across types",
                "xAxisKey": "type",
                "data": results_by_type_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#427730"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'results_by_type' failed: %s", exc)

        # Top 10 countries (bar chart)
        try:
            top_countries_data = _rows(cur, sql_top_countries, params)
            charts["top_countries"] = {
                "chartType": "bar",
                "title": f"Top 10 Countries by Innovations{label_suffix}",
                "description": "Countries with the most reported innovation results",
                "xAxisKey": "country",
                "data": top_countries_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#0065BD"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'top_countries' failed: %s", exc)

        # IRL distribution (bar chart)
        try:
            irl_data = _rows(cur, sql_irl, params)
            charts["irl_distribution"] = {
                "chartType": "bar",
                "title": f"Innovation Readiness Levels{label_suffix}",
                "description": "Distribution of innovations across IRL 0-9 scale",
                "xAxisKey": "level",
                "data": irl_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#7AB800"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'irl_distribution' failed: %s", exc)

        # Top 10 initiatives (bar chart)
        try:
            top_initiatives_data = _rows(cur, sql_top_initiatives, params)
            charts["top_initiatives"] = {
                "chartType": "bar",
                "title": f"Top 10 Initiatives by Innovations{label_suffix}",
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
            "year": year,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/dashboard/prms-stats")
async def prms_dashboard_stats(
    year: Optional[int] = Query(
        None,
        description="Filter the dashboard to a single reporting year (2022-2025). "
        "Omit for the all-years portfolio view.",
    ),
):
    """Return PRMS dashboard KPIs and chart data.

    Pass ``?year=2025`` to slice the dashboard to a single reporting year; omit
    it for the all-years portfolio view. Results are cached in-memory for 5
    minutes per year. If the PRMS database is unavailable a 503 is returned.
    Partial data is returned when individual queries fail. An invalid year
    yields a 400.
    """
    if year is not None and year not in _VALID_YEARS:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid year",
                "detail": f"year must be one of {sorted(_VALID_YEARS)} or omitted.",
            },
        )

    cache_key = year  # None for all-years, else the int year

    # Return cached data if still fresh
    now = time.monotonic()
    if cache_key in _cache and (now - _cache_ts.get(cache_key, 0.0)) < _CACHE_TTL:
        return _cache[cache_key]

    # Fetch fresh data
    try:
        data = _fetch_prms_data(year=year)
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
    _cache[cache_key] = data
    _cache_ts[cache_key] = now

    return data
