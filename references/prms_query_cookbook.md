# PRMS Query Cookbook
**Status:** Authoritative — patterns here supersede ad-hoc SQL in conversations.  
**Last verified:** 2026-06-14 against June 13 DB snapshot  
**DB path:** `$PRMS_DB_PATH` (env var) or fallback from prms_dashboard.py

---

## Quick Reference: Canonical Numbers (June 13 DB)

| Metric | All-years | 2022 | 2023 | 2024 | 2025 |
|--------|-----------|------|------|------|------|
| Innovation Development (type 7) — alive-in-year (**DEFAULT**) | —¹ | **477** | **872** | **1,016** | **1,185** |
| Innovation Development (type 7) — latest-phase dedup (alt) | **1,852**² | 62 | 160 | 445 | 963+222=1,185 |
| Innovation Use (type 2) — naive | 675 | — | — | — | — |
| Innovation Package (type 10) — naive | 96 | — | — | — | — |

¹ "Alive-in-year" is a per-year concept — sums across years exceed unique innovations because a code reporting in multiple years is counted multiple times. The all-years headline always uses the latest-phase dedup (1,852).  
² All-years total = 1,630 W1/W2 (latest-dedup) + 222 bilateral = 1,852. Always use this for the headline "total innovations" KPI.

---

## Recipe 1: All-Years Total Innovations (the headline KPI)

**When to use:** User asks "how many innovations total" or "all years" without a year filter.  
**Design rule:** This must match the `total_innovations` KPI card on the dashboard.

### What / Why
The all-years total is computed as:
- W1/W2: latest-phase dedup across all reporting years, type 7, source='Result', status_id=2, is_active=1
- Bilateral W3: source='API', status_id=6, is_active=1, type 7 (= 222, all 2025)
- Total = 1,630 + 222 = **1,852**

Using "latest-phase dedup" for W1/W2 here avoids double-counting result_codes that reported across multiple years.

### SQL
```sql
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
SELECT
    (SELECT COUNT(*) FROM canon WHERE result_type_id = 7) AS w1w2,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE result_type_id = 7 AND source = 'API' AND status_id = 6 AND is_active = 1) AS bilateral
;
-- Total = w1w2 + bilateral = 1,852
```

**Expected output:** w1w2=1630, bilateral=222, total=1852

---

## Recipe 2: Latest-Phase Dedup by Year (alternative/PowerBI view)

**When to use:** User explicitly asks for "latest data per innovation" or "PowerBI latest" view.  
**⚠️ This is NOT the default per-year count.** Use Recipe 3 (alive-in-year) for the default.

### What / Why
Each innovation is counted in the year of its LATEST reporting phase (W2, W4, W6 of the 4-phase cycle). This is the PowerBI "custom latest" option. It assigns each innovation to exactly one year (the most recent year it reported), so totals across years add up to exactly 1,630 (W1/W2 without bilateral).

### SQL
```sql
-- Per-year latest-phase count for type 7 (W1/W2 only)
WITH ord(v, o) AS (VALUES (1, 0), (3, 1), (4, 2), (6, 3)),
cand AS (
    SELECT r.result_code, r.id, r.result_type_id, r.reported_year_id, o.o AS phord
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
SELECT reported_year_id, COUNT(*) as count
FROM canon WHERE result_type_id = 7
GROUP BY reported_year_id ORDER BY reported_year_id;
```

**Expected output:** 2022=62, 2023=160, 2024=445, 2025=963  
**Sum check:** 62+160+445+963 = 1,630 ✅

---

## Recipe 3: Alive-in-Year Count (DEFAULT per-year count) ✅

**When to use:** User asks "how many innovations in [year X]" without an explicit "latest" qualifier. This is the default per-year interpretation.

### What / Why
An innovation counts for year X if it has AT LEAST ONE active, Quality-Assessed result row with `reported_year_id = X`. A result_code that reported in 2022, 2023, and 2025 counts for all three years separately.

**Why this is the correct default:**
- "Innovations in 2023" = innovations that were actively reporting in 2023, regardless of whether they continued into later years
- Latest-phase dedup (Recipe 2) answers a different question: "which year was each innovation last active?" — it assigns each code to exactly one year
- The dashboard `?year=2023` view shows alive-in-2023 data, not "innovations whose latest phase is 2023"

### Scope routing rule
**The alive-in-year set is the base population for ALL per-year breakdowns.**
When computing "innovations in 2023 by country/type/initiative/IRL", the scope is the 872 alive-in-2023 innovations. Join the breakdown dimension table to the same alive-in-year result rows.

### SQL

**W1/W2 component (per year — all years at once):**
```sql
SELECT reported_year_id, COUNT(DISTINCT result_code) AS alive_count
FROM result
WHERE result_type_id = 7
  AND source = 'Result'
  AND is_active = 1
  AND status_id = 2
GROUP BY reported_year_id
ORDER BY reported_year_id;
-- Output: 2022=477, 2023=872, 2024=1016, 2025=963
```

**Combined W1/W2 + bilateral, parameterized for year X:**
```sql
SELECT COUNT(DISTINCT result_code) AS alive_in_year
FROM result
WHERE result_type_id = 7
  AND reported_year_id = :year
  AND (
      (source = 'Result' AND is_active = 1 AND status_id = 2)   -- W1/W2
      OR
      (source = 'API'    AND is_active = 1 AND status_id = 6)   -- Bilateral W3
  );
-- Returns: 2022→477, 2023→872, 2024→1016, 2025→1185
```

**Breakdown query pattern (alive-in-year scope → per dimension):**
```sql
-- Example: innovations by country for year X (alive-in-year)
SELECT c.name AS country, COUNT(DISTINCT r.result_code) AS count
FROM result r
JOIN result_country rc ON rc.result_id = r.id AND rc.is_active = 1
JOIN clarisa_countries c ON rc.country_id = c.id
WHERE r.result_type_id = 7
  AND r.source = 'Result'
  AND r.is_active = 1
  AND r.status_id = 2
  AND r.reported_year_id = :year
GROUP BY c.name ORDER BY count DESC LIMIT 10;
-- Same pattern for IRL (JOIN results_innovations_dev) and initiatives (JOIN results_by_inititiative)
```

**Expected output (verified against June 13 DB):**

| Year | W1/W2 | Bilateral | Total |
|------|-------|-----------|-------|
| 2022 | 477 | 0 | **477** |
| 2023 | 872 | 0 | **872** |
| 2024 | 1,016 | 0 | **1,016** |
| 2025 | 963 | 222 | **1,185** |

---

## Recipe 4: All-Years Results-by-Type Chart

**When to use:** Building the dashboard pie/bar chart showing breakdown by innovation type.  
**Design rule:** Each chart bucket MUST equal its corresponding KPI card.

### What / Why
- Type 7 (Innovation Development): uses canonical all-years count = 1,852 (Recipe 1). Chart bucket = total_innovations KPI.
- Type 2 (Innovation Use): uses naive is_active=1 count = 675. Matches innovation_uses KPI. Canonical count differs (known open item).
- Type 10 (Innovation Package): uses naive is_active=1 count = 96. Matches innovation_packages KPI. No type-10 rows satisfy source='Result'/status_id=2 in this DB (known open item).

### SQL
```sql
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
SELECT 'Innovation Use' AS type,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE is_active = 1 AND result_type_id = 2) AS count
UNION ALL
SELECT 'Innovation Package' AS type,
    (SELECT COUNT(DISTINCT result_code) FROM result
     WHERE is_active = 1 AND result_type_id = 10) AS count
ORDER BY count DESC;
```

**Expected output:** Innovation Development=1852, Innovation Use=675, Innovation Package=96

---

## Recipe 5: Per-Year KPI — `?year=X` Dashboard Endpoint ✅

**When to use:** Dashboard `?year=X` — headline `total_innovations` KPI for a specific reporting year.  
**Implementation:** `_SQL_YEAR_INNOVATIONS` + `_SQL_YEAR_BILATERAL` in `prms_dashboard.py`

### SQL

**W1/W2 component (`_SQL_YEAR_INNOVATIONS`):**
```sql
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7
  AND source = 'Result'
  AND is_active = 1
  AND status_id = 2
  AND reported_year_id = :year;
-- 2022=477, 2023=872, 2024=1016, 2025=963
```

**Bilateral component (`_SQL_YEAR_BILATERAL`, added separately):**
```sql
SELECT COUNT(DISTINCT result_code) FROM result
WHERE result_type_id = 7 AND source = 'API'
  AND status_id = 6 AND is_active = 1
  AND reported_year_id = :year;
-- 2025=222, other years=0
```

**API response fields (per-year):**
```json
{
  "kpis": {
    "total_innovations": 1185,           // combined W1/W2 + bilateral
    "total_innovations_w1w2": 963,       // callout: W1/W2 component
    "total_innovations_bilateral": 222   // callout: bilateral component
  }
}
```

**Expected results (verified):**
| `?year=` | `total_innovations` | `w1w2` | `bilateral` |
|----------|--------------------|---------|-----------  |
| 2022 | 477 | 477 | 0 |
| 2023 | 872 | 872 | 0 |
| 2024 | 1,016 | 1,016 | 0 |
| 2025 | **1,185** | 963 | 222 |

---

## Recipe 6: Innovation Use — Per-Year Count

**When to use:** User asks how many Innovation Use (type 2) results in year X.  
**Status:** Currently uses year-scoped query with dedup CTE. Open item whether this is correct.

### SQL (from _SQL_YEAR_USES in prms_dashboard.py)
```sql
-- ⚠️ This uses status_id=2 + source='Result' + dedup, which may diverge from naive count
-- See prms_data_guide.md § 11 Open Items
WITH _CANON_YEAR_IDS_CTE AS (
    -- [see prms_dashboard.py for current implementation]
)
SELECT COUNT(*) FROM canon WHERE result_type_id = 2 AND reported_year_id = :year;
```

---

## Recipe 7: Innovation Package — Per-Year Count

**When to use:** User asks how many Innovation Package (type 10) results in year X.  
**Status:** Open item. No type-10 rows satisfy source='Result'/status_id=2 in all-years view.

### SQL
```sql
-- ⚠️ See prms_data_guide.md § 11 Open Items
-- Naive: SELECT COUNT(DISTINCT result_code) FROM result WHERE result_type_id=10 AND is_active=1 AND reported_year_id=:year
```

---

## Anti-Patterns ❌

### DO NOT use the naive all-years count for type 7
```sql
-- ❌ WRONG — returns 2,003 (inflated by multi-phase codes + missing status_id filter)
SELECT COUNT(DISTINCT result_code) FROM result WHERE result_type_id = 7 AND is_active = 1;
```

### DO NOT filter candidates to type 7 before deduping
```sql
-- ❌ WRONG — pre-filtering distorts the multi-type candidate pool
WITH cand AS (
    SELECT * FROM result
    WHERE result_type_id = 7  -- ← WRONG: filter should be AFTER the dedup
      AND source = 'Result' AND is_active = 1 AND status_id = 2
)
```
The correct pattern: build the candidate set across ALL result types first, then filter to result_type_id = 7 at the end.

---

## Open Items (Pending Investigation)

### OI-1: Alive-in-year per-year SQL ✅ RESOLVED (2026-06-14)
SQL confirmed in `analysis/task-alive-in-year-sql-result.md`. Filter: `result_type_id=7, source='Result', is_active=1, status_id=2, reported_year_id=:year`. Outputs: 477/872/1016/963. Implemented in prms_dashboard.py. See Recipe 3.

### OI-2: Innovation Use canonicalization
Naive=675, canon CTE=550, export=~624. Root cause unknown. See prms_data_guide.md § 11.2.

### OI-3: Innovation Package source/status anomaly  
Zero type-10 rows satisfy source='Result'/status_id=2. See prms_data_guide.md § 11.3.

### OI-4: Alive-in-year for types 2 and 10
Once OI-1 is resolved for type 7, same treatment needed for types 2 and 10.
