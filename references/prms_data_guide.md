# PRMS Data Guide — Innovation Analytics Agent

**Purpose:** Authoritative, query-ready guide for answering user questions about CGIAR **innovations** from the PRMS database. This guide is anchored on a set of **locked canonical counts** confirmed through an extensive reconstruction investigation (2026-06-14) against the live 13-June-2026 DB dump (`prdb_fresh.sqlite`) and the official CGIAR Results Dashboard "Export table" Excel output. Every count, every SQL template, and every caveat below is consistent with those locked numbers. When in doubt, the numbers in **Section 1** are ground truth.

> Companion file: `prms_schema_reference.md` (full table-by-table schema). This guide is the practical query/counting layer on top of it. Where the two disagree on a counting method, **this guide wins** — the schema reference predates the corrected dedup investigation.

---

## 1. Canonical Counts (Ground Truth)

These are **locked**. They were reproduced exactly from `prdb_fresh.sqlite` using the corrected dedup CTE (Section 4) and verified 1:1 against the dashboard's Innovation Developments Excel export (1,630 rows; one row per logical innovation).

### Innovation Developments — W1/W2 pooled, ALIVE-IN-YEAR (the default per-year count)

| Year | W1/W2 alive-in-year | W3/bilateral | **Total** |
|------|---------------------|--------------|-----------|
| 2022 | **477** | 0 | **477** |
| 2023 | **872** | 0 | **872** |
| 2024 | **1,016** | 0 | **1,016** |
| 2025 | **963** | **222** | **1,185** |

**Alive-in-year** counts an innovation in year X if it has at least one active, Quality-Assessed (`status_id=2`) W1/W2 (`source='Result'`) row with `reported_year_id = X`. A result_code that reported in 2022, 2023, and 2025 counts in all three years. These are the correct default answers for "how many innovations in year X?"

Verified SQL (June 13 DB):
```sql
SELECT reported_year_id, COUNT(DISTINCT result_code) AS alive_count
FROM result WHERE result_type_id=7 AND source='Result' AND is_active=1 AND status_id=2
GROUP BY reported_year_id ORDER BY reported_year_id;
-- 2022=477, 2023=872, 2024=1016, 2025=963 ✓
```

### Innovation Developments — LATEST-PHASE DEDUP (alternative view)

The **latest-phase dedup** assigns each innovation to exactly ONE year — the year of its most-recent Quality-Assessed phase. These numbers match the CGIAR Results Dashboard Excel export's `Year` column value-counts (one row per logical innovation).

| Year | W1/W2 latest-phase | Notes |
|------|-------------------|-------|
| 2022 | **62** | Innovations whose LAST phase is in 2022 |
| 2023 | **160** | |
| 2024 | **445** | |
| 2025 | **963** | + 222 bilateral = **1,185** grand total |

**Sum check:** 62+160+445+963 = **1,630** W1/W2 unique innovations (all-years headline before bilateral). See Section 4 for the dedup CTE. Use this view only when the user explicitly asks for "latest data per innovation" or "PowerBI latest" — it is NOT the default per-year count.

### Innovation Developments — 2025 grand total (pooled + bilateral)

**1,185** = **963** W1/W2 pooled + **222** W3/bilateral (Approved). Only 2025 has bilateral Innovation Developments; 2022–2024 bilateral = 0.

| Year | W1/W2 | W3/bilateral | Total |
|------|-------|--------------|-------|
| 2022 | 62  | 0   | 62   |
| 2023 | 160 | 0   | 160  |
| 2024 | 445 | 0   | 445  |
| 2025 | 963 | 222 | **1,185** |

### Reclassification caveat (why an older method gave 83 / 172)

A previous dedup pattern produced **83** for 2022 and **172** for 2023 because it **pre-filtered `result_type_id = 7` *before* resolving each result_code's latest reporting phase**. **33 result_codes** (21 in 2022, 12 in 2023) were **reclassified to a different result type in a later phase** (16 → Other output, 14 → Innovation use, 1 each → Policy change / Other outcome / Knowledge product). The old method froze them at their early type-7 phase and over-counted. The corrected CTE resolves the latest QAed-active phase across **all** result types first, **then** filters on type 7 — dropping exactly those 33 codes and reproducing 62 / 160. (2024/2025 are unaffected because a later reclassification can only push a code *out* of an earlier year, and there is no phase after 2025.)

These are the only correct numbers. **Do not report 83 / 172 — they are a known artifact of the deprecated method.**

---

## 2. What "Innovations" Means by Default

When a user says **"innovations"** with no qualifier, default to **Innovation Developments = `result_type_id = 7`**. This is the count the dashboard headlines and the count every canonical number in Section 1 refers to.

| result_type_id | Meaning | Notes |
|----------------|---------|-------|
| **7** | **Innovation Development** | **The default "innovations".** |
| **2** | **Innovation Use** | NOT 8, NOT 9 — common mistake. Type 8 = Other output, type 9 = Impact contribution. |
| **10** | **Innovation Package / IPSR** | Scaling-readiness assessments. Uses the IPSR phase chain (versions 2/5/7). |

**Callout convention:** Whenever you answer an "innovations" question, append a short note such as:
> *Count covers Innovation Developments (type 7). Innovation Use (type 2) and Innovation Packages/IPSR (type 10) are reported separately and are excluded here.*

This prevents silent conflation of three distinct result types that users often lump together as "innovations".

---

## 3. Database Overview

PRMS (Performance and Results Management System) is CGIAR's authoritative results-reporting database. The local dump holds **~32,026 result rows (27,811 active)** across **200 tables**, spanning reporting years **2022–2025**.

### Two portfolio eras
- **Initiatives era (2022–2024):** initiative codes `INIT-XX`, `SGP-XX`. Versions 1/2/3/4/5 (`portfolio_id = 2`).
- **Programs & Accelerators era (2025+):** Science Program codes `SP01`…`SP13`, plus Impact Platforms `PLAT-01`…`PLAT-05`. Versions 6/7 (`portfolio_id = 3`).

A query that ignores the era boundary mixes two different organizational structures. The `clarisa_initiatives` table holds both eras' codes (62 rows).

### Phase / version chain
Reporting is **phase-based**. Each `result_code` gets a fresh `result.id` row each phase it is reported in. Two parallel chains:

| Chain | Versions (`version_id`) | Use for |
|-------|-------------------------|---------|
| **Reporting** | `1` (2022) → `3` (2023) → `4` (2024) → `6` (2025, active) | Innovation Development (7), Innovation Use (2), most types |
| **IPSR** | `2` (2023) → `5` (2024) → `7` (2025, active) | Innovation Packages (10) only |

Phase-ordering values used by the dedup CTE: Reporting `(1,0),(3,1),(4,2),(6,3)`; IPSR `(2,0),(5,1),(7,2)`.

### Result types (active row counts, all phases — NOT deduped)
Knowledge product 12,850; **Innovation development 4,416**; Capacity sharing 4,033; Other output 3,670; **Innovation use 976**; Complementary innovation 610; Policy change 537; Other outcome 460; **Innovation Package/IPSR 223**; Capacity change 26 (deprecated); Impact contribution 2. (These are raw `is_active=1` row counts, useful for scale only — they are *not* dedup counts. See Section 4 for the correct counting method.)

---

## 4. Dedup CTE — The Correct Method

> **This is the single most important section.** Every canonical count in Section 1 comes from this CTE. It replaces every earlier dedup pattern in any companion file.

A `result_code` is a stable logical innovation; `result.id` is a per-phase submission row. To count innovations you must collapse to **one canonical row per `result_code` = its latest QAed-active reporting phase across ALL result types**, and only then filter to the type you want.

```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),   -- Reporting chain phase order
-- STAGE 1: candidate set = QAed-active rows of ANY type.
-- Searching across ALL types (not just type 7) is what lets us find the TRUE latest phase.
cand_all AS (
  SELECT r.result_code, r.reported_year_id, r.id, r.result_type_id, o.o AS phord
  FROM result r JOIN ord o ON o.v = r.version_id
  WHERE r.source = 'Result'      -- W1/W2 pooled funding
    AND r.is_active = 1          -- soft-delete filter (load-bearing)
    AND r.status_id = 2          -- Quality Assessed = dashboard-published gate (load-bearing)
),
-- STAGE 2: for each code, find the phase-order of its latest QAed-active phase.
pick_all AS (SELECT result_code, MAX(phord) AS m FROM cand_all GROUP BY result_code),
-- STAGE 3: keep the rows tied at that latest phase.
latest_all AS (
  SELECT c.* FROM cand_all c
  JOIN pick_all p ON p.result_code = c.result_code AND p.m = c.phord
),
-- STAGE 4: collapse any same-phase ties to a single canonical row (MAX(id)).
latest_innov AS (
  SELECT result_code, reported_year_id, id, result_type_id
  FROM latest_all
  WHERE id = (SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code = latest_all.result_code)
)
-- STAGE 5 (filter LAST): keep only codes whose latest phase is STILL the type you want.
SELECT reported_year_id AS year, COUNT(*) AS n
FROM latest_innov
WHERE result_type_id = 7          -- <-- change this to count other types (2 = Use)
GROUP BY reported_year_id
ORDER BY reported_year_id;
-- OUTPUT (verified): 2022=62, 2023=160, 2024=445, 2025=963
```

### Why each constraint is load-bearing
- **`status_id = 2` (Quality Assessed)** — the de-facto "published to dashboard" gate for W1/W2 results. Without it the candidate set includes Editing/Submitted drafts.
- **`is_active = 1`** — excludes soft-deleted rows. Two export-included codes (3241, 5938) have a *later* non-type-7 phase that is **not** QAed/active; restricting the latest-phase search to `status_id=2 AND is_active=1` correctly keeps them while dropping the 33 reclassified codes. This constraint is what makes the count exact.
- **`source = 'Result'`** — W1/W2 pooled only. Bilateral (`source='API'`) follows a different status vocabulary and is counted separately (Section 5).

### ⚠️ The deprecated pattern — DO NOT USE
The wrong pattern puts `result_type_id = 7` **inside** the candidate set (`cand`), before resolving the latest phase:

```sql
-- WRONG — produces inflated 2022=83, 2023=172 (do not use)
cand AS (
  SELECT ... FROM result r JOIN ord o ON o.v = r.version_id
  WHERE r.result_type_id = 7   -- <-- pre-filtering type here is the bug
    AND r.source='Result' AND r.is_active=1 AND r.status_id=2
)
```
This freezes a reclassified code at its early type-7 phase and over-counts 2022/2023. **Always filter result_type LAST (Stage 5), never in the candidate set.**

### Adapting to other result types
- **Innovation Use:** change the final `WHERE result_type_id = 7` to `= 2`. Output: 2022=39, 2023=102, 2024=63, 2025=346.
- **Innovation Packages / IPSR:** use the **IPSR phase chain** in the `ord` VALUES list instead: `(2,0),(5,1),(7,2)`, then filter `result_type_id = 10`.

---

## 5. W1/W2 vs W3/Bilateral Funding Sources

PRMS carries two funding-window pipelines with **different status vocabularies** and **different inclusion gates**. Never silently mix them.

| Window | `source` | Inclusion gate | Status meaning |
|--------|----------|----------------|----------------|
| **W1/W2 pooled** | `'Result'` | `status_id = 2 AND is_active = 1` | 2 = Quality Assessed |
| **W3 / bilateral** | `'API'` | `status_id = 6 AND is_active = 1` | 6 = Approved (API Bilateral Status) |

### The bilateral gate is deliberate and documented
`result_status` flags statuses **5/6/7 as "API Bilateral Status"** (Pending Review / Approved / Rejected) — a separate vocabulary reserved for the bilateral pipeline. The authoritative PRMS reference states the dashboard policy verbatim: **"show ONLY approved results on the dashboard"** (rejected = failed QA, excluded). So `status_id = 6` is the bilateral analogue of W1/W2's `status_id = 2`. With `is_active = 1`, the Approved bilateral population is exactly **222** distinct codes (2025 only) — the precise gap between 963 and the 1,185 dashboard total.

### Bilateral query
```sql
-- W3/bilateral Innovation Developments (Approved only)
SELECT reported_year_id AS year, COUNT(DISTINCT result_code) AS bilateral_n
FROM result
WHERE result_type_id = 7
  AND source = 'API'
  AND status_id = 6        -- Approved (API Bilateral Status); excludes Pending(5)/Rejected(7)
  AND is_active = 1
GROUP BY reported_year_id
ORDER BY reported_year_id;
-- OUTPUT: 2025 = 222 (2022/2023/2024 = 0)
```

**Presentation rule:** When reporting a 2025 total, always show the funding breakdown as a callout: *"1,185 total = 963 W1/W2 pooled + 222 W3/bilateral (Approved). Bilateral results carry a dashboard disclaimer."*

---

## 6. Common Query Templates

> All templates are SQLite, validated against `prdb_fresh.sqlite`. Join satellites on `result.id`; dedup/count on `result_code`. Filter `is_active = 1` everywhere.

### 6.1 Count by year — W1/W2 only (the default — ALIVE-IN-YEAR)
```sql
SELECT reported_year_id, COUNT(DISTINCT result_code) AS alive_count
FROM result WHERE result_type_id=7 AND source='Result' AND is_active=1 AND status_id=2
GROUP BY reported_year_id ORDER BY reported_year_id;
```
**Output: 2022=477, 2023=872, 2024=1016, 2025=963.**

For the latest-phase dedup alternative (62/160/445/963), use the corrected dedup CTE from Section 4.

### 6.2 Count by year — including bilateral (dashboard grand total)
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (
  SELECT r.result_code, r.reported_year_id, r.id, r.result_type_id, o.o AS phord
  FROM result r JOIN ord o ON o.v = r.version_id
  WHERE r.source = 'Result' AND r.is_active = 1 AND r.status_id = 2
),
pick_all AS (SELECT result_code, MAX(phord) AS m FROM cand_all GROUP BY result_code),
latest_all AS (
  SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code = c.result_code AND p.m = c.phord
),
latest_innov AS (
  SELECT result_code, reported_year_id, id, result_type_id FROM latest_all
  WHERE id = (SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code = latest_all.result_code)
),
w12 AS (
  SELECT reported_year_id AS year, COUNT(*) AS w1w2_n
  FROM latest_innov WHERE result_type_id = 7 GROUP BY reported_year_id
),
bilateral AS (
  SELECT reported_year_id AS year, COUNT(DISTINCT result_code) AS bilateral_n
  FROM result WHERE result_type_id=7 AND source='API' AND status_id=6 AND is_active=1
  GROUP BY reported_year_id
),
years AS (SELECT DISTINCT year FROM w12 UNION SELECT year FROM bilateral)
SELECT y.year,
       COALESCE(w12.w1w2_n, 0)            AS w1w2,
       COALESCE(bilateral.bilateral_n, 0) AS bilateral,
       COALESCE(w12.w1w2_n, 0) + COALESCE(bilateral.bilateral_n, 0) AS total
FROM years y
LEFT JOIN w12       ON w12.year = y.year
LEFT JOIN bilateral ON bilateral.year = y.year
ORDER BY y.year;
-- OUTPUT: 2022=62, 2023=160, 2024=445, 2025=1185 (963+222)
```

### 6.3 Count by initiative / program (Submitter)
Wrap the dedup CTE, then join the lead-initiative junction. **Note the table-name typo `results_by_inititiative` (double-t) and column `inititiative_id`.**
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (SELECT r.result_code, r.id, r.result_type_id, o.o AS phord
  FROM result r JOIN ord o ON o.v=r.version_id
  WHERE r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick_all AS (SELECT result_code, MAX(phord) m FROM cand_all GROUP BY result_code),
latest_all AS (SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code=c.result_code AND p.m=c.phord),
latest_innov AS (SELECT result_code, id, result_type_id FROM latest_all
  WHERE id=(SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code=latest_all.result_code))
SELECT ci.official_code, ci.name, COUNT(DISTINCT li.result_code) AS n
FROM latest_innov li
JOIN results_by_inititiative rbi ON rbi.result_id = li.id AND rbi.initiative_role_id = 1 AND rbi.is_active = 1
JOIN clarisa_initiatives ci ON ci.id = rbi.inititiative_id
WHERE li.result_type_id = 7
GROUP BY ci.official_code, ci.name
ORDER BY n DESC;
-- Top rows (2025-era programs lead): SP09=190, SP03=148, SP02=137, SP01=105, INIT-13=102 ...
-- initiative_role_id: 1 = lead/primary submitter; other values = contributing.
```

### 6.4 Count by result level
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (SELECT r.result_code, r.id, r.result_type_id, r.result_level_id, o.o AS phord
  FROM result r JOIN ord o ON o.v=r.version_id WHERE r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick_all AS (SELECT result_code, MAX(phord) m FROM cand_all GROUP BY result_code),
latest_all AS (SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code=c.result_code AND p.m=c.phord),
latest_innov AS (SELECT result_code, result_level_id, result_type_id FROM latest_all
  WHERE id=(SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code=latest_all.result_code))
SELECT rl.name AS level, COUNT(*) n
FROM latest_innov li JOIN result_level rl ON rl.id = li.result_level_id
WHERE li.result_type_id = 7
GROUP BY rl.name ORDER BY n DESC;
-- Innovation Developments are level 4 = "Output" (all of them).
```

### 6.5 Breakdown by IRL (Innovation Readiness Level, 0–9)
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (SELECT r.result_code, r.id, r.result_type_id, o.o AS phord
  FROM result r JOIN ord o ON o.v=r.version_id WHERE r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick_all AS (SELECT result_code, MAX(phord) m FROM cand_all GROUP BY result_code),
latest_all AS (SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code=c.result_code AND p.m=c.phord),
latest_innov AS (SELECT result_code, id, result_type_id FROM latest_all
  WHERE id=(SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code=latest_all.result_code))
SELECT cirl.level AS irl, cirl.name, COUNT(DISTINCT li.result_code) AS n
FROM latest_innov li
JOIN results_innovations_dev d ON d.results_id = li.id        -- NOTE: results_id (with 's')
JOIN clarisa_innovation_readiness_level cirl ON cirl.id = d.innovation_readiness_level_id
WHERE li.result_type_id = 7
GROUP BY cirl.level, cirl.name ORDER BY cirl.level;
-- IRL ids are 11-20 in the lookup; cirl.level is the 0-9 integer shown in the export.
-- Distribution skews high: level 9 (Proven Innovation) = 268, level 7 (Prototype) = 245.
```

### 6.6 Impact-tag summary (gender / climate / nutrition / env / poverty)
All five impact dimensions share the **one** `gender_tag_level` lookup (titles: Not targeted / Significant / Principal; descriptions "(0)…/(1)…/(2)…").
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (SELECT r.result_code, r.id, r.result_type_id, r.gender_tag_level_id, o.o AS phord
  FROM result r JOIN ord o ON o.v=r.version_id WHERE r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick_all AS (SELECT result_code, MAX(phord) m FROM cand_all GROUP BY result_code),
latest_all AS (SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code=c.result_code AND p.m=c.phord),
latest_innov AS (SELECT result_code, gender_tag_level_id, result_type_id FROM latest_all
  WHERE id=(SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code=latest_all.result_code))
SELECT gtl.title AS gender_tag, COUNT(*) n
FROM latest_innov li LEFT JOIN gender_tag_level gtl ON gtl.id = li.gender_tag_level_id
WHERE li.result_type_id = 7
GROUP BY gtl.title ORDER BY n DESC;
-- Output: Not targeted 840, Significant 663, Principal 127.
-- Swap gender_tag_level_id for climate_change_tag_level_id / nutrition_tag_level_id /
-- environmental_biodiversity_tag_level_id / poverty_tag_level_id to pivot a different dimension.
-- Caveat: climate tags are systematically under-applied; never treat them as a complete census.
```

### 6.7 Innovation Use count by year (type 2)
Identical corrected dedup pattern, filter `result_type_id = 2` at the final stage.
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand_all AS (SELECT r.result_code, r.reported_year_id, r.id, r.result_type_id, o.o AS phord
  FROM result r JOIN ord o ON o.v=r.version_id WHERE r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick_all AS (SELECT result_code, MAX(phord) m FROM cand_all GROUP BY result_code),
latest_all AS (SELECT c.* FROM cand_all c JOIN pick_all p ON p.result_code=c.result_code AND p.m=c.phord),
latest_innov AS (SELECT result_code, reported_year_id, id, result_type_id FROM latest_all
  WHERE id=(SELECT MAX(l2.id) FROM latest_all l2 WHERE l2.result_code=latest_all.result_code))
SELECT reported_year_id AS year, COUNT(*) AS n
FROM latest_innov WHERE result_type_id = 2
GROUP BY reported_year_id ORDER BY reported_year_id;
-- OUTPUT: 2022=39, 2023=102, 2024=63, 2025=346.
```

### 6.8 Alive-in-year count (SECONDARY — never the default)
Counts each code in **every** year it had an active QAed submission (a stock/cumulative view), NOT the latest-phase snapshot. **Diverges 5–7x from dashboard for 2022/2023 — only use when the user explicitly asks "active in year X" / "in-flight in year X".**
```sql
-- SECONDARY METRIC. Not dashboard-aligned. Label clearly in any answer.
SELECT reported_year_id AS year, COUNT(DISTINCT result_code) AS alive_n
FROM result
WHERE result_type_id = 7 AND source = 'Result' AND is_active = 1 AND status_id = 2
  AND version_id IN (1,3,4,6)
GROUP BY reported_year_id ORDER BY reported_year_id;
-- OUTPUT (alive-in-year, crude): 2022=477, 2023=872, 2024=1016, 2025=963. See Section 9.
```

---

## 7. Key Table Reference

| Table | Rows | Use |
|-------|------|-----|
| `result` | 32,026 (27,811 active) | Central fact table. Every result anchored here. One row per `result_code` per phase. |
| `results_innovations_dev` | 4,867 | Innovation Development (type 7) detail. Join `results_id → result.id`. |
| `results_innovations_use` | 599 | Innovation Use (type 2) detail. Join `results_id → result.id`. |
| `result_innovation_package` | — | IPSR / package-level (PK = `result.id`). |
| `result_by_innovation_package` | — | IPSR component innovations. Join `result_innovation_package_id`. |
| `version` | 7 | Phase/year/portfolio. Join `result.version_id`. |
| `result_type` / `result_level` / `result_status` | 11 / 4 / 7 | Lookups for type / level / status. |
| `results_by_inititiative` (TYPO: double-t) | 38,839 | result ↔ initiative/program. `initiative_role_id` 1=lead, other=contributing. Column `inititiative_id`. |
| `clarisa_initiatives` | 62 | `official_code` (INIT-XX / SP01… / PLAT-0X), `name`. |
| `results_center` | 46,300 | result ↔ center; flags `is_primary`, `is_leading_result`. Join `center_id → clarisa_center.code`. |
| `clarisa_center` | 17 | center `code` / `acronym`. `institutionId` (camelCase) → `clarisa_institutions.id`. |
| `results_by_institution` | 78,345 | partners/actors; `institution_roles_id` (2=Partner, 1=Actor, 5/6=IPSR partners). |
| `result_country` / `result_region` | 34,479 / 21,406 | geography. Join on `result_id`. |
| `evidence` | 49,784 | evidence links + cross-cutting flags per result. Join `result_id`. |
| `gender_tag_level` | 3 | SHARED lookup for ALL FIVE impact tags. |
| `clarisa_innovation_readiness_level` | 10 | IRL (`level` 0-9; `id` 11-20). |
| `clarisa_innovation_use_levels` | 10 | IUL (`level` 0-9). |

### Key conventions (critical)
- **`result.id`** = phase-specific row key → **join all satellites on this**.
- **`result.result_code`** = stable logical key across phases → **dedup / count on this**.
- **Satellite join-column naming varies:** `results_id` (with 's') on `results_innovations_dev`, `results_innovations_use`, `results_knowledge_product`; `result_id` (no 's') on `results_by_inititiative`, `result_country`, `result_region`, `results_center`, `evidence`. Always check the column name per table.
- **Preserve schema typos verbatim in SQL:** `results_by_inititiative`, `inititiative_id`, `accesible`, `has_unkown_using`, `non_pooled_projetct_budget`, `toc_pahse_id`.
- **Multi-valued fields** (centers, partners, countries, evidence) are one-to-many — use sub-queries / `GROUP_CONCAT`, never a naive JOIN that multiplies rows before a count.

---

## 8. Field Mapping Guide (Excel ↔ DB)

The dashboard **Innovation Developments "Export table"** Excel has **41 columns** (verified against `Innovation_Developments_export_data_table_results_20261306_151859CET.xlsx`, 1,630 rows). Column order and exact names:

| # | Excel column | DB source |
|---|--------------|-----------|
| 0 | Result code | `result.result_code` |
| 1 | Year | `result.reported_year_id` (= latest-phase year) |
| 2 | PDF link | built: `reporting.cgiar.org/.../result-details/{result_code}?phase={version_id}` |
| 3 | Funding source | `result.source` ('Result' → "Pooled funding (W1/W2)") |
| 4 | Submitter | `clarisa_initiatives.official_code` via `results_by_inititiative` role=1 |
| 5 | Level | `result_level.name` (always "Output" for dev) |
| 6 | Type | `result_type.name` ("Innovation development") |
| 7 / 8 | Title / Description | `result.title` / `result.description` |
| 9 | Lead contact person | `result.lead_contact_person` |
| 10–14 | Gender / Climate change / Nutrition tag / Environmental biodiversity tag / Poverty tag level | `result.*_tag_level_id` → `gender_tag_level.description` |
| 15 | Actors | `result_actors` → `actor_type.name` + counts |
| 16 / 17 | Is KRS / KRS link | `result.is_krs` / `result.krs_url` |
| 18 | Legacy ID | `result.legacy_id` |
| 19 | Contributing CGIAR reporting entities | `results_by_inititiative` role≠1 → official_code (GROUP_CONCAT) |
| 20 | Bilateral projects | `results_by_projects` → `clarisa_projects` |
| 21 | Result leader | `results_center.is_leading_result=1` → center code |
| 22 | Contributing centers | `results_center.is_primary=0` → center code |
| 23 | TOC results | (2025 ToC nodes are CLARISA-API only — often empty locally) |
| 24 | Partners | `results_by_institution` role=2 → `clarisa_institutions.name` |
| 25 / 26 | Countries / CGIAR regions | `result_country` / `result_region` → CLARISA names |
| 27 | Linked results | `linked_result` → other result_codes |
| 28 | Short title | `results_innovations_dev.short_title` |
| 29 | Innovation characterization | `clarisa_innovation_characteristic.name` via `innovation_characterization_id` |
| 30 | Innovation nature | `clarisa_innovation_type.name` via `innovation_nature_id` (PK = `code`) |
| 31 / 32 | Is new variety? / number_of_varieties | `results_innovations_dev.is_new_variety` / `.number_of_varieties` |
| 33–35 | Developers / Collaborators / Acknowledgement | `results_innovations_dev.innovation_developers` / `_collaborators` / `innovation_acknowledgement` |
| 36 | Readiness level | `clarisa_innovation_readiness_level.level` (the **0-9 INTEGER**, not the name) |
| 37 | Evidences explanation | `results_innovations_dev.evidences_justification` |
| 38–40 | Evidence 1–3 | pivot `evidence` (is_active=1) by row-number per result_id |

**Innovation Use export** is a UNION of type 2 + type 10; type-specific columns include *Use level* (`clarisa_innovation_use_levels.level` via `results_innovations_use.innovation_use_level_id`), *Users by actor* (`result_actors`), and IPSR-only fields (scaling ambition, components, experts) where readiness/use/potential scores are **computed**, not stored — fetch from the dashboard/PowerBI if a user needs them.

---

## 9. Secondary Metrics and Caveats

### Alive-in-year (stock metric — never the default)
Counts each innovation in **every** year it had an active QAed submission, not just the year of its most-recent phase. Known divergences (corrected dedup vs alive-in-year):

| Year | Dashboard (latest-phase) | Alive-in-year (crude) |
|------|--------------------------|------------------------|
| 2022 | 62  | **477** |
| 2023 | 160 | **872** |
| 2024 | 445 | **1016** |
| 2025 | 963 | 963 |

(A related "lifecycle-spanning" variant gives 477 / 892 / 1017 / 963 — it additionally counts a code in years bracketed by its first and last phase even if a phase was skipped. The 2023 difference, 872 vs 892, is 20 codes with a skipped reporting phase.) These diverge **5–7x** from dashboard counts for 2022/2023. **Offer only when the user explicitly asks "active in year X" or "in-flight in year X," and label it clearly as a stock metric, not the dashboard count.**

### Reclassification caveat
**33 result_codes** (2022: 21; 2023: 12) were reclassified from Innovation Development to other types in later phases (16 → Other output type 8, 14 → Innovation use type 2, 1 each → Policy change / Other outcome / Knowledge product). They are **correctly excluded** from Innovation Development counts by the Section-4 CTE because it filters type **last**. This is the entire reason the deprecated method reported 83/172 instead of 62/160.

### DB dedup vs dashboard — fully reproducible
The dashboard's per-year counts **ARE reproducible from the SQLite DB alone** using the corrected CTE. **No external semantic-model layer is involved.** The earlier hypothesis of a "manually-refreshed `CGIAR_result_dashboard` semantic model gate" was disproven — the 33-code gap is entirely explained by result-type reclassification. The Excel export *is* the dashboard's "Export table" output (one year filter at a time), so the export `Year` column is a faithful proxy for the live dashboard's per-year figures.

### Other standing caveats
- **Climate tags** are systematically under-applied — never treat `climate_change_tag_level_id > 1` as a complete census of climate-relevant innovations.
- **IPSR computed scores** (Readiness/Use level, Readiness/Potential score) are not stored as a single column — fetch from the dashboard/PowerBI dataflow.
- **Lead contact person** shows ~7% drift between export and DB (name-resolution order across phases).
- **`reported_year_id` is NULL** for ~610 rows — they fall outside the four reporting years.
- **Live dashboard not anonymously queryable** — it is an authenticated SPA. Per-year figures above are confirmed against the export, which the reference documents as the dashboard's own per-year output.

---

## 10. Result Types Reference

| id | name | Active rows (all phases) | Detail table |
|----|------|--------------------------|--------------|
| 1 | Policy change | 537 | `results_policy_changes` |
| **2** | **Innovation use** | 976 | `results_innovations_use` |
| 3 | Capacity change (deprecated) | 26 | — |
| 4 | Other outcome | 460 | — |
| 5 | Capacity sharing for development | 4,033 | `results_capacity_developments` |
| 6 | Knowledge product | 12,850 | `results_knowledge_product` |
| **7** | **Innovation development** (default "innovations") | 4,416 | `results_innovations_dev` |
| 8 | Other output | 3,670 | — |
| 9 | Impact contribution | 2 | — |
| **10** | **Innovation Package / IPSR** | 223 | `result_innovation_package`, `result_by_innovation_package` |
| 11 | Complementary innovation | 610 | — |

> Active-row counts are raw `is_active=1` row counts (not deduped), for scale only. To **count innovations**, always use the corrected dedup CTE (Section 4) on `result_code`, never `COUNT(*)`.

### result_status reference
| id | status_name | Notes |
|----|-------------|-------|
| 1 | Editing | draft |
| 2 | Quality Assessed | **W1/W2 dashboard-published gate** |
| 3 | Submitted | |
| 4 | Discontinued | |
| 5 | Pending Review | API Bilateral Status |
| 6 | Approved | **W3/bilateral dashboard-published gate** (API Bilateral Status) |
| 7 | Rejected | API Bilateral Status (failed QA — excluded) |

---

## 11. Open Items — Innovation Use and Innovation Package Canonicalization

These items are explicitly deferred from Phase 2 and must not be silently
resolved without a dedicated investigation.

### 11.1 Innovation Development — FULLY CANONICALIZED ✅

Innovation Development (result_type_id=7) is the only type that has been fully
canonicalized in the dashboard. The methodology is:

1. Latest-phase dedup CTE: candidate set spans ALL result types
   (source='Result', is_active=1, status_id=2); latest phase selected by
   version_id priority order (1→3→4→6); tie-break by MAX(id).
2. Filter to result_type_id=7 at the end → W1/W2 all-years total = 1,630
   (2022=62, 2023=160, 2024=445, 2025=963).
3. Plus bilateral W3 (source='API', status_id=6, is_active=1,
   result_type_id=7) = 222 (all 2025).
4. Headline = 1,630 + 222 = **1,852**.

All dashboard outputs (KPI card, results_by_type chart bucket, per-year
endpoints) use this methodology. There is no "2,003" or "2,003-anywhere"
contradiction remaining.

### 11.2 Innovation Use (result_type_id=2) — open ⚠️

Three counts exist and do not reconcile:

| Source | Count | Filter |
|--------|-------|--------|
| Dashboard KPI (`_SQL_INNOVATION_USES`) | **675** | `is_active=1, result_type_id=2` (naive) |
| Canon CTE (dedup + status_id=2) | **550** | `source='Result', is_active=1, status_id=2, result_type_id=2` |
| Export (row count from CSV) | **~624** | per-year filter on the PRMS export |

The 675 figure is used in both the KPI card and the results_by_type chart
bucket so they are currently consistent (no visible contradiction), but the
methodology differs from the Innovation Development treatment.

**Root cause not yet investigated.** Possible explanations: Innovation Use
results carry a different status_id distribution; some active type-2 rows have
source='API'; the export uses a different year filter. **Do not assume 675 is
canonical** — it has not been cross-checked against the live PRMS dashboard.

**Action required:** Run the canonical counts by status_id for result_type_id=2;
compare against the export and the live dashboard export for a single year;
decide whether to adopt a canonical methodology or document 675 as the
agreed-upon figure.

### 11.3 Innovation Package (result_type_id=10) — open ⚠️

| Source | Count | Filter |
|--------|-------|--------|
| Dashboard KPI (`_SQL_INNOVATION_PACKAGES`) | **96** | `is_active=1, result_type_id=10` (naive) |
| Canon CTE (dedup + status_id=2) | **0** | `source='Result', is_active=1, status_id=2, result_type_id=10` |

The canon CTE returns zero because **no type-10 rows in the current DB snapshot
satisfy `source='Result' AND status_id=2`**. This means Innovation Packages
are either submitted under a different source (e.g. 'API', or 'Initiative
bilateral result') or carry a different status_id than the W1/W2 gate (2 =
Quality Assessed).

This is a data characteristic of the DB snapshot, not a query bug. The 96
figure used by the KPI and chart bucket may be correct, or it may be
over-counting active-but-not-QAed packages.

**Action required:** Check `SELECT DISTINCT source, status_id, COUNT(*) FROM
result WHERE result_type_id=10 AND is_active=1 GROUP BY source, status_id;`
to understand the source/status landscape for type-10 results. Compare against
the live PRMS dashboard package count. Define and document the canonical
methodology before any further changes to the Innovation Package count.

### 11.4 Dashboard chart — current state (Phase 2 close)

The all-years `results_by_type` chart currently uses:

| Type | Methodology | Expected value | KPI match? |
|------|-------------|----------------|------------|
| Innovation Development | Canon CTE + bilateral | **1,852** | ✅ |
| Innovation Use | Naive (`is_active=1`) | **675** | ✅ |
| Innovation Package | Naive (`is_active=1`) | **96** | ✅ |

All three chart buckets match their KPI cards (no visible contradictions).
Types 2 and 10 are intentionally left on naive counts until their canonical
methodologies are established in a follow-up investigation.
