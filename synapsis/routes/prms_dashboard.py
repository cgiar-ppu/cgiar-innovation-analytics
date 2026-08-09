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
    "/Users/smithai/workspace/coding/PRMSDB/fresh_13June2026/prdb_fresh.sqlite",
)

# ---------------------------------------------------------------------------
# SQL Queries
# ---------------------------------------------------------------------------

# All-years total results KPI.
# FIX (wave 2, F-3): added `source='Result' AND status_id=2` so the all-years
# card uses the same QAed definition as its per-year twin
# (_SQL_YEAR_TOTAL_RESULTS). Previously is_active=1-only returned 2,759, which
# counted unQAed + bilateral rows the per-year cards exclude; the aligned
# QAed-only count is 2,274.
_SQL_TOTAL_RESULTS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND source = 'Result' AND status_id = 2
  AND result_type_id IN (2, 7, 10);
"""

# Canonical all-years Innovation Development count: latest-phase dedup across
# ALL result types first (source='Result', is_active=1, status_id=2), THEN
# filter to result_type_id=7. This mirrors the per-year _CANON_YEAR_IDS_CTE
# methodology and is the only way to get the correct W1/W2 total without
# double-counting reclassified codes.
#   W1/W2 all-years = 62+160+445+963 = 1,630
# Previously used a naive COUNT(DISTINCT) WHERE is_active=1 AND result_type_id=7
# (no status_id filter, no latest-phase dedup) which returned 2,003 (+151).
# W3/bilateral (source='API', status_id=6) is added separately via
# _SQL_ALL_YEARS_BILATERAL so the headline = 1,630 + 222 = 1,852.
_SQL_TOTAL_INNOVATIONS = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, r.result_type_id, o.o AS phord
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
)
SELECT COUNT(*) FROM canon WHERE result_type_id = 7;
"""

# Bilateral (W3/API) Innovation Developments — all years combined. Added to
# total_innovations in the no-year portfolio view to match the same
# W1/W2 + bilateral logic applied in the per-year branch.
_SQL_ALL_YEARS_BILATERAL = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7 AND source = 'API' AND status_id = 6 AND is_active = 1;
"""

# Canonical innovation-use count: count by result_type_id (type 2) on the
# result table. The previous results_innovations_use join undercounted
# (488 vs 669) for the same reason as above.
# NOTE: This no-year query uses is_active=1 only (no status_id filter), which
# is less strict than the year-scoped _SQL_YEAR_USES (status_id=2). The
# canonical benchmark for all-years Innovation Use has not been established, so
# the filter mismatch is flagged but not changed here.
_SQL_INNOVATION_USES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id = 2;
"""

# All-years active initiatives KPI.
# FIX (wave 2, F-3): added `source='Result' AND status_id=2` to match the
# per-year _SQL_YEAR_INITIATIVES definition. (Count is unchanged at 54 in this
# DB, but the filter is now consistent with the per-year card.)
_SQL_ACTIVE_INITIATIVES = """
SELECT COUNT(DISTINCT i.id)
FROM clarisa_initiatives i
JOIN results_by_inititiative rbi ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1 AND r.source = 'Result' AND r.status_id = 2
  AND r.result_type_id IN (2, 7, 10);
"""

# All-years countries-covered KPI.
# FIX (wave 2, F-3): added `source='Result' AND status_id=2` to match the
# per-year _SQL_YEAR_COUNTRIES definition. Previously is_active=1-only returned
# 124; the aligned QAed-only count is 117.
# Geography note (Cheatsheet rule 5): this is a distinct-country count on
# result_country and is correct as a country metric. There is no region/"Africa"
# slicer in this endpoint, so the country-OR-region UNION rule is not in play
# here; if such a slicer is ever added, it MUST implement that UNION.
_SQL_COUNTRIES_COVERED = """
SELECT COUNT(DISTINCT rc.country_id)
FROM result_country rc
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1
  AND r.source = 'Result' AND r.status_id = 2
  AND r.result_type_id IN (2, 7, 10);
"""

_SQL_INNOVATION_PACKAGES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1 AND result_type_id = 10;
"""

# All-years results-by-type chart.
#
# Design rule: every bucket MUST equal its corresponding KPI card so a user
# never sees two different numbers for the same thing on the default view.
#
# - Innovation Development (type 7): latest-phase dedup CTE across ALL result
#   types (source='Result', is_active=1, status_id=2) then filter to type 7
#   = 1,630 W1/W2, PLUS bilateral W3 (source='API', status_id=6) = 222.
#   Chart bucket = 1,852 = total_innovations KPI. Fully canonicalized. ✅
#
# - Innovation Use (type 2): naive is_active=1 count, matching
#   _SQL_INNOVATION_USES. Chart bucket = 675 = innovation_uses KPI. The
#   canonical (dedup + status_id=2) count yields 550, and the export yields
#   ~624. These divergences are a known open item (see prms_data_guide.md
#   § Open Items). Using naive here keeps chart and KPI in sync.
#
# - Innovation Package (type 10): naive is_active=1 count, matching
#   _SQL_INNOVATION_PACKAGES. Chart bucket = 96 = innovation_packages KPI.
#   CORRECTION (wave 2, F-4): the previous comment here claimed "the canonical
#   (dedup + status_id=2) count is 0 because no type-10 rows satisfy
#   source='Result' AND status_id=2." That is FACTUALLY WRONG. In this DB there
#   are 164 type-10 rows / 74 distinct codes with source='Result' AND
#   status_id=2 AND is_active=1. The dedup CTE returns 0 for type 10 only
#   because its phase-ordering map `ord(v, o) AS (VALUES (1,0),(3,1),(4,2),(6,3))`
#   covers version_id ∈ {1,3,4,6}, while these type-10 QAed rows live on
#   version_id ∈ {2,5,7} (v2=47, v5=64, v7=53 rows). The inner
#   `JOIN ord o ON o.v = r.version_id` therefore silently drops every type-10
#   row → canon = 0. This is a version-coverage gap in the phase map, NOT an
#   absence of data. The same gap likely explains part of the type-2 naive(675)
#   vs canon(550) divergence, since type-2 QAed rows also span versions outside
#   {1,3,4,6}.
#   # OPEN ITEM (OI-3 / OI-4): the correct canonical per-year/all-years type-10
#   (and type-2) figure is genuinely undecided — either extend `ord` to cover
#   versions {2,5,7} (which would also move the type-2 canon count) or use a
#   non-phase dedup for these types. Do NOT invent a number; the naive
#   is_active=1 counts are used here intentionally to keep chart == KPI.
_SQL_RESULTS_BY_TYPE = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, r.result_type_id, o.o AS phord
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
)
SELECT 'Innovation Development' AS type,
    (SELECT COUNT(*) FROM canon WHERE result_type_id = 7) +
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE result_type_id = 7 AND source = 'API'
       AND status_id = 6 AND is_active = 1) AS count
UNION ALL
SELECT 'Innovations in use' AS type,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE is_active = 1 AND result_type_id = 2) AS count
UNION ALL
SELECT 'Innovation Package' AS type,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE is_active = 1 AND result_type_id = 10) AS count
ORDER BY count DESC;
"""

# All-years top countries.
# FIX (wave 2, F-2): added `source='Result' AND status_id=2` so the ranking is
# scoped to the QAed dashboard population (matching the per-year branch and the
# KPI cards). Without it the chart counted unQAed + bilateral rows (Kenya 357 →
# 316, etc.). Geography note (Cheatsheet rule 5): this is a country breakdown
# keyed on result_country only and is correct as-is. If a region/"Africa"
# geography slicer is ever added here, it MUST use the country-ISO-3 OR
# region-UN-M49 UNION rule — never one side alone.
_SQL_TOP_COUNTRIES = """
SELECT c.name AS country, COUNT(DISTINCT r.result_code) AS count
FROM result_country rc
JOIN clarisa_countries c ON rc.country_id = c.id
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1
  AND r.source = 'Result' AND r.status_id = 2
  AND r.result_type_id IN (2, 7, 10)
GROUP BY c.name
ORDER BY count DESC
LIMIT 10;
"""

# All-years IRL distribution — BOTH funding windows (W1/W2 + W3/bilateral).
#
# FIX (wave 2, F-1): the previous query joined results_innovations_dev to
# result with ONLY is_active=1 on both — no result_type / source / status /
# latest-phase dedup. It returned 1,963 distinct codes (unQAed + every
# reporting phase of every code).
#
# FIX (2026-06-23): include BOTH funding windows. The candidate set is the
# W1/W2 latest-phase canon (source='Result', status_id=2) UNION the W3/bilateral
# Approved set (source='API', status_id=6; 2025-only, one row per code). We then
# JOIN results_innovations_dev — which NATURALLY drops any code (W1/W2 or
# bilateral) that has no IRL record — and count distinct codes per level.
# Earlier this chart was W1/W2-only on the FALSE assumption that "bilateral has
# no IRL data": that is wrong (e.g. result_code 28583 is a bilateral Innovation
# Development with a valid IRL 9), and it under-counted scaling-ready innovations.
# Letting the JOIN filter is the correct, self-maintaining pattern.
_SQL_IRL_DISTRIBUTION = """
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, r.result_type_id, o.o AS phord
    FROM result r JOIN ord o ON o.v = r.version_id
    WHERE r.source = 'Result' AND r.is_active = 1 AND r.status_id = 2
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (
    SELECT c.* FROM cand c
    JOIN pick p ON p.result_code = c.result_code AND p.m = c.phord
),
canon_w12 AS (
    SELECT l.result_code, l.id, l.result_type_id FROM latest l
    WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code)
),
canon_bilateral AS (
    SELECT r.result_code, MAX(r.id) AS id, 7 AS result_type_id
    FROM result r
    WHERE r.source = 'API' AND r.status_id = 6 AND r.is_active = 1 AND r.result_type_id = 7
    GROUP BY r.result_code
),
canon AS (
    SELECT result_code, id, result_type_id FROM canon_w12
    UNION ALL
    SELECT result_code, id, result_type_id FROM canon_bilateral
)
SELECT cirl.name AS level, COUNT(DISTINCT cn.result_code) AS count
FROM canon cn
JOIN results_innovations_dev rid ON rid.results_id = cn.id AND rid.is_active = 1
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
WHERE cn.result_type_id = 7
GROUP BY cirl.name, cirl.id
ORDER BY cirl.id;
"""

# All-years top initiatives.
# FIX (wave 2, F-2): added `source='Result' AND status_id=2` so the ranking
# matches the QAed dashboard population (Scaling for Impact 438 → 270, etc.).
# SP##/INIT-## era mixing is acceptable here because this is an all-years view
# (the era tripwire only applies to single-year slices).
_SQL_TOP_INITIATIVES = """
SELECT i.short_name AS initiative, COUNT(DISTINCT r.result_code) AS count
FROM results_by_inititiative rbi
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1 AND rbi.initiative_role_id = 1
  AND r.source = 'Result' AND r.status_id = 2
  AND r.result_type_id IN (2, 7, 10)
GROUP BY i.short_name
ORDER BY count DESC
LIMIT 10;
"""

# ---------------------------------------------------------------------------
# Year-scoped queries
# ---------------------------------------------------------------------------
# When a specific year is requested, the dashboard uses ALIVE-IN-YEAR counting:
# an Innovation Development (type 7) is counted for year X if it has at least
# one active, Quality-Assessed W1/W2 row with reported_year_id = X. A
# result_code that reported in 2022, 2023, and 2025 counts for ALL three years.
#
# This is the correct default per-year interpretation ("innovations active in
# year X"). The alternative "latest-phase dedup" (which assigns each code to
# exactly ONE year — its most recent) is the PowerBI custom-latest view and
# yields 62/160/445/963; it is available via the prms_query_cookbook.md but
# is NOT the dashboard default.
#
# Alive-in-year W1/W2 counts (verified against June 13 DB):
#   2022 = 477, 2023 = 872, 2024 = 1,016, 2025 = 963 + 222 bilateral = 1,185
#
# The alive-in-year scope flows to ALL per-year breakdowns (countries, IRL,
# initiatives, type chart). Each breakdown joins directly from the alive-in-year
# result rows, so "innovations in 2023 by country" uses the 872-innovation set.
#
# NOTE: The _CANON_YEAR_IDS_CTE (latest-phase dedup, see prms_query_cookbook.md
# Recipe 2) is no longer used for per-year views. It is retained in the all-
# years queries (_SQL_TOTAL_INNOVATIONS, _SQL_RESULTS_BY_TYPE) for the headline
# KPI which counts each innovation exactly once across all years.

# Bilateral (W3/API) Innovation Developments for the requested year — added to
# the headline count so it matches the "include W3/bilateral" totals.
# Expected: 2025=222, 2022/2023/2024=0.
_SQL_YEAR_BILATERAL = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7 AND source = 'API' AND status_id = 6
  AND is_active = 1 AND reported_year_id = :year;
"""

# Headline Innovation Developments KPI for the year — alive-in-year W1/W2 count.
# Bilateral is added separately via _SQL_YEAR_BILATERAL in _fetch_prms_data.
# Expected: 2022=477, 2023=872, 2024=1016, 2025=963 (pre-bilateral).
_SQL_YEAR_INNOVATIONS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7
  AND source = 'Result'
  AND is_active = 1
  AND status_id = 2
  AND reported_year_id = :year;
"""

# Innovation Use (type 2) and Innovation Package (type 10) for the year use the
# dashboard filter scoped by reported_year_id. These types do not carry the same
# multi-year phase-chain dedup concern at the dashboard's granularity, so a
# direct reported_year_id slice is acceptable and clearly year-labelled in the UI.
# All per-year KPI/breakdown queries include BOTH funding windows by default:
#   W1/W2 pooled  -> source='Result' AND status_id=2  ("Quality Assessed")
#   W3/bilateral  -> source='API'    AND status_id=6  ("Approved", separate QA gate)
# Bilateral is fully quality-assured via its own gate; never require status_id=2
# of bilateral rows and never pre-filter a breakdown to W1/W2-only.
_SQL_YEAR_USES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1
  AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
  AND result_type_id = 2 AND reported_year_id = :year;
"""

_SQL_YEAR_PACKAGES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1
  AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
  AND result_type_id = 10 AND reported_year_id = :year;
"""

# Total results KPI for the year (all three innovation types, both windows).
_SQL_YEAR_TOTAL_RESULTS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1
  AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
  AND result_type_id IN (2, 7, 10) AND reported_year_id = :year;
"""

_SQL_YEAR_INITIATIVES = """
SELECT COUNT(DISTINCT i.id)
FROM clarisa_initiatives i
JOIN results_by_inititiative rbi ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.result_type_id IN (2, 7, 10) AND r.reported_year_id = :year;
"""

_SQL_YEAR_COUNTRIES = """
SELECT COUNT(DISTINCT rc.country_id)
FROM result_country rc
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.result_type_id IN (2, 7, 10)
  AND r.reported_year_id = :year;
"""

# Charts scoped to the alive-in-year Innovation Development set for the year.
# Each breakdown joins directly from alive-in-year result rows so the scope
# is consistent with the headline KPI (type 7, source='Result', is_active=1,
# status_id=2, reported_year_id=:year).
_SQL_YEAR_TOP_COUNTRIES = """
SELECT c.name AS country, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN result_country rc ON rc.result_id = r.id AND rc.is_active = 1
JOIN clarisa_countries c ON rc.country_id = c.id
WHERE r.result_type_id = 7
  AND r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.reported_year_id = :year
GROUP BY c.name
ORDER BY count DESC
LIMIT 10;
"""

# Per-year IRL distribution — BOTH funding windows. The JOIN to
# results_innovations_dev drops any code (W1/W2 or bilateral) with no IRL
# record, so bilateral innovations that DO carry IRL (e.g. code 28583, IRL 9)
# are counted; never pre-filter to source='Result'.
_SQL_YEAR_IRL_DISTRIBUTION = """
SELECT cirl.name AS level, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN results_innovations_dev rid ON rid.results_id = r.id AND rid.is_active = 1
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
WHERE r.result_type_id = 7
  AND r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.reported_year_id = :year
GROUP BY cirl.name, cirl.id
ORDER BY cirl.id;
"""

_SQL_YEAR_TOP_INITIATIVES = """
SELECT i.short_name AS initiative, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN results_by_inititiative rbi ON rbi.result_id = r.id AND rbi.initiative_role_id = 1
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
WHERE r.result_type_id = 7
  AND r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.reported_year_id = :year
GROUP BY i.short_name
ORDER BY count DESC
LIMIT 10;
"""

# Results-by-type chart for a year. Innovation Development bucket = alive-in-year
# W1/W2 + bilateral, matching the total_innovations KPI (design rule: chart bucket
# must equal its corresponding KPI card). Types 2 and 10 use Quality-Assessed
# per-year counts (no dedup needed for these types at year granularity).
_SQL_YEAR_RESULTS_BY_TYPE = """
SELECT 'Innovation Development' AS type,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE result_type_id = 7 AND source = 'Result' AND is_active = 1 AND status_id = 2
       AND reported_year_id = :year)
    +
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE result_type_id = 7 AND source = 'API' AND is_active = 1 AND status_id = 6
       AND reported_year_id = :year) AS count
UNION ALL
SELECT 'Innovations in use' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1
      AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
      AND result_type_id = 2 AND reported_year_id = :year)
UNION ALL
SELECT 'Innovation Package' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1
      AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
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
            year using ALIVE-IN-YEAR counting: an Innovation Development (type 7)
            is counted for year X if it has at least one active, Quality-Assessed
            W1/W2 row in that year. Expected W1/W2 totals: 2022=477, 2023=872,
            2024=1016, 2025=963 (+222 bilateral = 1185). All breakdown charts
            (countries, IRL, initiatives, type) use the same alive-in-year scope.
            If None, returns the all-years portfolio view (headline = 1,852).

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

        # Add W3/bilateral to total_innovations so the headline reconciles with
        # per-year views in both branches:
        #   per-year:  W1/W2 alive-in-year (e.g. 963) + bilateral for that year (222) = 1,185
        #   all-years: W1/W2 latest-dedup (1,630) + bilateral all years (222) = 1,852
        # For per-year responses, also expose the W1/W2 and bilateral components
        # as separate callout fields so the UI can show the funding-source breakdown.
        bilateral_sql = _SQL_YEAR_BILATERAL if is_year else _SQL_ALL_YEARS_BILATERAL
        bilateral_label = "year_bilateral" if is_year else "all_years_bilateral"
        try:
            bilateral_count = _scalar(cur, bilateral_sql, params)
            if is_year:
                kpis["total_innovations_w1w2"] = kpis.get("total_innovations", 0)
                kpis["total_innovations_bilateral"] = bilateral_count
            kpis["total_innovations"] += bilateral_count
        except sqlite3.Error as exc:
            logger.error("KPI query '%s' failed: %s", bilateral_label, exc)
            if is_year:
                kpis["total_innovations_w1w2"] = kpis.get("total_innovations", 0)
                kpis["total_innovations_bilateral"] = 0

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
# GEOGRAPHY NOTE (wave 2, F-5): this endpoint exposes NO region/"Africa" geo
# slicer — the only geography dimension is the country breakdown, keyed on
# result_country, which is correct for a per-country metric. So the Cheatsheet
# rule-5 country-OR-region UNION is not in play here (it is absent, not
# violated). If a region/geography filter (e.g. an "Africa" toggle) is ever
# added to this route, it MUST implement the UNION of:
#   - result_region   (UN-M49 region_id IN (2,202,11,14,15,17,18)), AND
#   - result_country  (the 54 African ISO-3 codes via clarisa_countries)
# and MUST NOT rely on clarisa_countries_regions (empty in this DB). Counting
# only one side silently undercounts (2024 Africa IRL7+: region-only=111,
# country-only=203, comprehensive UNION=264). Add a regression test pinning
# those numbers if such a slicer is introduced.

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
