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
from collections.abc import Sequence
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("synapsis.routes.prms_dashboard")

router = APIRouter(prefix="/api", tags=["prms-dashboard"])

# Years the year filter accepts. "All years" is represented by an empty
# selection.
_VALID_YEARS = {2022, 2023, 2024, 2025}

# Portfolio-era labels — the SAME mapping the chat scope filter uses
# (synapsis/routes/scope.py), so the dashboard and the agent can never disagree
# about which era an entity belongs to. See references/prms_data_guide.md §3.
_ERA_LABELS = {
    2: "Initiatives (2022–2024)",
    3: "Programs & Accelerators (2025+)",
}

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

# All-years top portfolio entities (Science Programs / Initiatives).
#
# F1 + F14 (2026-08-09): this chart used to rank raw `short_name` values with
# no portfolio identity, so a 2025 view silently said "Initiatives" when the
# entities are in fact Science Programs. It now selects `official_code` and
# `portfolio_id` as well, and the route renders era-aware labels/titles reusing
# the mapping from synapsis/routes/scope.py (portfolio_id 2 = "Initiatives
# (2022–2024)", 3 = "Programs & Accelerators (2025+)").
#
# SCOPE CHANGE (F1, documented): the previous all-years query counted result
# types 2, 7 and 10 while the per-year query counted type 7 only, so "All
# years" and "2025" measured different things under the same "by Innovations"
# title. The all-years ranking now uses the SAME canonical Innovation
# Development set as the total_innovations KPI — the W1/W2 latest-phase canon
# UNION the W3/bilateral Approved set, i.e. the 1,852 headline innovations.
# Effect on this DB: SP09 270 -> 224, INIT-11 145 -> 70 (the delta is types
# 2/10 and non-latest phases, which never belonged under "by Innovations").
#
# `MIN(...)` on short_name/portfolio_id collapses the handful of duplicate
# official_code rows in clarisa_initiatives (INIT-11, INIT-12 — identical
# short_name and portfolio_id in both rows). The prefix filter drops the
# internal placeholder rows (MP-01/02, OFF-01, OPLAT-01/02), which carry an
# empty short_name and previously rendered as blank bars.
_SQL_TOP_INITIATIVES = """
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
scope AS (
    SELECT result_code, id FROM canon_w12 WHERE result_type_id = 7
    UNION ALL
    SELECT result_code, id FROM canon_bilateral
)
SELECT i.official_code AS code,
       MIN(i.short_name) AS short_name,
       MIN(i.portfolio_id) AS portfolio_id,
       COUNT(DISTINCT s.result_code) AS count
FROM scope s
JOIN results_by_inititiative rbi ON rbi.result_id = s.id AND rbi.initiative_role_id = 1
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
WHERE i.official_code LIKE 'INIT-%' OR i.official_code LIKE 'SGP-%'
   OR i.official_code LIKE 'PLAT-%' OR i.official_code LIKE 'SP%'
GROUP BY i.official_code
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
#
# MULTI-YEAR (F7): every year-scoped query below carries the literal token
# `__YEARS__` inside `reported_year_id IN (__YEARS__)`. At runtime
# `_bind_years()` swaps that token for a bound-parameter list (`:y0, :y1, …`)
# built from the validated year selection, so the SQL text is never
# string-interpolated with user input.
#
# Semantics of a multi-year selection = ALIVE-IN-ANY-OF-THE-SELECTED-YEARS
# (an OR across years). Because every count is COUNT(DISTINCT result_code),
# a code that reported in 2024 AND 2025 is counted ONCE for the selection
# {2024, 2025} — no double counting across years (the F4 discipline). It
# follows that a multi-year total is NOT the sum of its single-year totals;
# it is the size of their union.
#
# A single-year selection produces `IN (:y0)`, which is semantically identical
# to the previous `= :year`, so single-year numbers are unchanged by design.

# Bilateral (W3/API) Innovation Developments for the requested year — added to
# the headline count so it matches the "include W3/bilateral" totals.
# Expected: 2025=222, 2022/2023/2024=0.
_SQL_YEAR_BILATERAL = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7 AND source = 'API' AND status_id = 6
  AND is_active = 1 AND reported_year_id IN (__YEARS__);
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
  AND reported_year_id IN (__YEARS__);
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
  AND result_type_id = 2 AND reported_year_id IN (__YEARS__);
"""

_SQL_YEAR_PACKAGES = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1
  AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
  AND result_type_id = 10 AND reported_year_id IN (__YEARS__);
"""

# Total results KPI for the year (all three innovation types, both windows).
_SQL_YEAR_TOTAL_RESULTS = """
SELECT COUNT(DISTINCT result_code) FROM result
WHERE is_active = 1
  AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
  AND result_type_id IN (2, 7, 10) AND reported_year_id IN (__YEARS__);
"""

_SQL_YEAR_INITIATIVES = """
SELECT COUNT(DISTINCT i.id)
FROM clarisa_initiatives i
JOIN results_by_inititiative rbi ON rbi.inititiative_id = i.id
JOIN result r ON r.id = rbi.result_id
WHERE r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.result_type_id IN (2, 7, 10) AND r.reported_year_id IN (__YEARS__);
"""

_SQL_YEAR_COUNTRIES = """
SELECT COUNT(DISTINCT rc.country_id)
FROM result_country rc
JOIN result r ON r.id = rc.result_id
WHERE r.is_active = 1 AND rc.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.result_type_id IN (2, 7, 10)
  AND r.reported_year_id IN (__YEARS__);
"""

# Charts scoped to the alive-in-year Innovation Development set for the year.
# Each breakdown joins directly from alive-in-year result rows so the scope
# is consistent with the headline KPI (type 7, source='Result', is_active=1,
# status_id=2, reported_year_id IN <selected years>).
_SQL_YEAR_TOP_COUNTRIES = """
SELECT c.name AS country, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN result_country rc ON rc.result_id = r.id AND rc.is_active = 1
JOIN clarisa_countries c ON rc.country_id = c.id
WHERE r.result_type_id = 7
  AND r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.reported_year_id IN (__YEARS__)
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
  AND r.reported_year_id IN (__YEARS__)
GROUP BY cirl.name, cirl.id
ORDER BY cirl.id;
"""

# Year-scoped top portfolio entities (F1 + F14). Same alive-in-year type-7
# scope as before — only the projection changed, so per-year counts are
# unchanged (2025: SP09 = 224, SP01 = 195, …). See _SQL_TOP_INITIATIVES for
# the MIN()/prefix-filter rationale.
_SQL_YEAR_TOP_INITIATIVES = """
SELECT i.official_code AS code,
       MIN(i.short_name) AS short_name,
       MIN(i.portfolio_id) AS portfolio_id,
       COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN results_by_inititiative rbi ON rbi.result_id = r.id AND rbi.initiative_role_id = 1
JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
WHERE r.result_type_id = 7
  AND r.is_active = 1
  AND ((r.source = 'Result' AND r.status_id = 2) OR (r.source = 'API' AND r.status_id = 6))
  AND r.reported_year_id IN (__YEARS__)
  AND (i.official_code LIKE 'INIT-%' OR i.official_code LIKE 'SGP-%'
       OR i.official_code LIKE 'PLAT-%' OR i.official_code LIKE 'SP%')
GROUP BY i.official_code
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
       AND reported_year_id IN (__YEARS__))
    +
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE result_type_id = 7 AND source = 'API' AND is_active = 1 AND status_id = 6
       AND reported_year_id IN (__YEARS__)) AS count
UNION ALL
SELECT 'Innovations in use' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1
      AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
      AND result_type_id = 2 AND reported_year_id IN (__YEARS__))
UNION ALL
SELECT 'Innovation Package' AS type, (
    SELECT COUNT(DISTINCT result_code) FROM result
    WHERE is_active = 1
      AND ((source = 'Result' AND status_id = 2) OR (source = 'API' AND status_id = 6))
      AND result_type_id = 10 AND reported_year_id IN (__YEARS__));
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
# Helpers: multi-year selection (F7)
# ---------------------------------------------------------------------------
def normalize_years(raw: Optional[Sequence[str | int]]) -> tuple[list[int], list[str]]:
    """Parse a ``years`` query-parameter value into a sorted, deduped year list.

    Accepts repeated params (``?years=2024&years=2025``) and/or comma lists
    (``?years=2024,2025``), in any mix. Returns ``(years, invalid_tokens)``.
    An empty ``years`` list means "All years".
    """
    if not raw:
        return [], []
    years: set[int] = set()
    invalid: list[str] = []
    for item in raw:
        for token in str(item).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = int(token)
            except ValueError:
                invalid.append(token)
                continue
            if value in _VALID_YEARS:
                years.add(value)
            else:
                invalid.append(token)
    return sorted(years), invalid


def _bind_years(sql: str, years: Sequence[int]) -> str:
    """Replace the ``__YEARS__`` token with a bound-parameter list."""
    return sql.replace("__YEARS__", ", ".join(f":y{i}" for i in range(len(years))))


def _year_params(years: Sequence[int]) -> dict[str, int]:
    """Build the ``{y0: 2024, y1: 2025}`` parameter dict for ``_bind_years``."""
    return {f"y{i}": y for i, y in enumerate(years)}


def _entity_label(code: str, short_name: Optional[str]) -> str:
    """Readable portfolio-entity label, e.g. "SP09 — Scaling for Impact".

    `\\xa0` (non-breaking space) shows up in several SP short names in
    clarisa_initiatives — same cleanup as synapsis/routes/scope.py.
    """
    name = (short_name or "").replace("\xa0", " ").strip()
    return f"{code} — {name}" if name else code


def _entity_chart_wording(portfolio_ids: Sequence[Optional[int]]) -> tuple[str, str]:
    """Return (noun, era_note) for a set of portfolio_ids present in the data.

    The noun drives the chart title, so a 2025 view says "Science Programs"
    and a 2022-2024 view says "Initiatives" — the F1 ask. A selection spanning
    both eras is labelled with both nouns rather than silently picking one
    (references/prms_data_guide.md §3 era tripwire).
    """
    eras = {pid for pid in portfolio_ids if pid is not None}
    if eras == {3}:
        return "Science Programs", _ERA_LABELS[3]
    if eras == {2}:
        return "Initiatives", _ERA_LABELS[2]
    if not eras:
        return "Programs / Initiatives", ""
    return (
        "Science Programs / Initiatives",
        " + ".join(_ERA_LABELS[pid] for pid in sorted(eras) if pid in _ERA_LABELS),
    )


def years_label(years: Sequence[int]) -> str:
    """Human-readable label for a year selection ("All years", "2024–2025")."""
    if not years:
        return "All years"
    ordered = sorted(years)
    if len(ordered) == 1:
        return str(ordered[0])
    # Contiguous runs collapse to a range; anything else is an explicit list.
    if ordered[-1] - ordered[0] == len(ordered) - 1:
        return f"{ordered[0]}–{ordered[-1]}"
    return ", ".join(str(y) for y in ordered)


# ---------------------------------------------------------------------------
# Core: fetch all dashboard data from the PRMS database
# ---------------------------------------------------------------------------
def _fetch_prms_data(years: Optional[Sequence[int]] = None) -> dict[str, Any]:
    """Connect to the PRMS SQLite database and run all dashboard queries.

    Args:
        years: Reporting years (2022-2025) to slice the dashboard to. The
            dashboard uses ALIVE-IN-YEAR counting: an Innovation Development
            (type 7) is counted for year X if it has at least one active,
            Quality-Assessed W1/W2 row in that year. Expected single-year
            W1/W2 totals: 2022=477, 2023=872, 2024=1016, 2025=963 (+222
            bilateral = 1185). A multi-year selection is alive-in-ANY of the
            selected years, deduped by result code (so it is the UNION of the
            single-year sets, never their sum). All breakdown charts
            (countries, IRL, programmes, type) use the same scope.
            An empty/None selection returns the all-years portfolio view
            (headline = 1,852).

    Returns the full API response dict. Raises FileNotFoundError if the
    database file does not exist, and sqlite3.Error on query failures.
    """
    if not os.path.isfile(_PRMS_DB_PATH):
        raise FileNotFoundError(f"PRMS database not found at: {_PRMS_DB_PATH}")

    selected = sorted(years or ())
    is_year = bool(selected)
    params: Optional[dict[str, int]] = _year_params(selected) if is_year else None
    label_suffix = f" ({years_label(selected)})" if is_year else ""

    def sql(text: str) -> str:
        """Bind the __YEARS__ token for year-scoped SQL; pass others through."""
        return _bind_years(text, selected) if is_year else text

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
        for key, kpi_sql in kpi_queries.items():
            try:
                kpis[key] = _scalar(cur, sql(kpi_sql), params)
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
            bilateral_count = _scalar(cur, sql(bilateral_sql), params)
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
            results_by_type_data = _rows(cur, sql(sql_results_by_type), params)
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
            top_countries_data = _rows(cur, sql(sql_top_countries), params)
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
            irl_data = _rows(cur, sql(sql_irl), params)
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

        # Top 10 portfolio entities — Science Programs / Initiatives (F1 + F14).
        #
        # Rendered as a HORIZONTAL bar chart so every entity keeps its full
        # readable name and its value is printed on the bar: the #1 entity is
        # legible outright, without hovering and without truncation (F14).
        # The response key stays `top_initiatives` for backward compatibility.
        try:
            entity_rows = _rows(cur, sql(sql_top_initiatives), params)
            noun, era_note = _entity_chart_wording([r.get("portfolio_id") for r in entity_rows])
            entity_data = [
                {
                    "entity": _entity_label(r.get("code", ""), r.get("short_name")),
                    "code": r.get("code", ""),
                    "era": _ERA_LABELS.get(r.get("portfolio_id"), "Other"),
                    "count": r.get("count", 0),
                }
                for r in entity_rows
            ]
            description = (
                f"CGIAR portfolio entities contributing the most Innovation "
                f"Developments, ranked by distinct result code"
            )
            if era_note:
                description += f" · {era_note}"
            charts["top_initiatives"] = {
                "chartType": "horizontalBar",
                "title": f"Top 10 {noun} by Innovations{label_suffix}",
                "description": description,
                "xAxisKey": "entity",
                "data": entity_data,
                "series": [{"key": "count", "label": "Innovations", "color": "#E37222"}],
            }
        except sqlite3.Error as exc:
            logger.error("Chart query 'top_initiatives' failed: %s", exc)

        return {
            "kpis": kpis,
            "charts": charts,
            # `year` is kept for backward compatibility: it is the single
            # selected year, or None for "All years" AND for any multi-year
            # selection (which has no single year). `years` is authoritative.
            "year": selected[0] if len(selected) == 1 else None,
            "years": selected,
            "years_label": years_label(selected),
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
    years: Optional[list[str]] = Query(
        None,
        description="Reporting years to slice the dashboard to (2022-2025). "
        "Repeat the parameter (?years=2024&years=2025) and/or pass a comma "
        "list (?years=2024,2025). Omit for the all-years portfolio view. "
        "Multiple years are ALIVE-IN-ANY-OF semantics, deduped by result code.",
    ),
    year: Optional[int] = Query(
        None,
        description="Deprecated single-year alias, kept for backward "
        "compatibility. Ignored when `years` is supplied.",
    ),
):
    """Return PRMS dashboard KPIs and chart data.

    Year selection (F7):

    - omit both params  -> the all-years portfolio view ("All years")
    - ``?year=2025``    -> single year (legacy alias, unchanged behaviour)
    - ``?years=2025``   -> single year, identical numbers to ``?year=2025``
    - ``?years=2024&years=2025`` or ``?years=2024,2025`` -> the UNION of both
      years' alive-in-year sets, deduped by result code (never the sum).

    Results are cached in-memory for 5 minutes per distinct year selection. If
    the PRMS database is unavailable a 503 is returned. Partial data is
    returned when individual queries fail. An invalid year yields a 400.
    """
    selected, invalid = normalize_years(years)
    if invalid:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid year",
                "detail": f"years must be drawn from {sorted(_VALID_YEARS)}; "
                f"rejected: {invalid}.",
            },
        )

    if not selected and year is not None:
        # Legacy single-year alias.
        if year not in _VALID_YEARS:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Invalid year",
                    "detail": f"year must be one of {sorted(_VALID_YEARS)} or omitted.",
                },
            )
        selected = [year]

    cache_key: Any = tuple(selected)  # () for all-years, else the sorted years

    # Return cached data if still fresh
    now = time.monotonic()
    if cache_key in _cache and (now - _cache_ts.get(cache_key, 0.0)) < _CACHE_TTL:
        return _cache[cache_key]

    # Fetch fresh data
    try:
        data = _fetch_prms_data(years=selected)
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
