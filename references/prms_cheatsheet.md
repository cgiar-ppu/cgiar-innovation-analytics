# PRMS Cheat Sheet — the 8 rules that prevent 90% of wrong answers

**Read this first. It is short on purpose.** Deeper detail lives in `prms_query_cookbook` and `prms_data_guide`; this page is the always-on muscle memory.

---

### 1. Count innovations by `result_code`, never by `id` or rows
The same innovation gets a new `result.id` every year but keeps its `result_code`. → `COUNT(DISTINCT result_code)`.

### 2. Default filter for innovation queries
```sql
result_type_id = 7        -- Innovation Development (the default "innovation")
AND source = 'Result'     -- W1/W2 pooled (the public dashboard); 'API' = W3/bilateral, never mix
AND is_active = 1
AND status_id = 2         -- "Quality Assessed" = published to dashboard (~2% residual is expected)
```

### 3. Year: if a year is in play, FILTER by it
If the user names a year — now or in an earlier turn (it **carries forward**) — your SQL **must** contain `reported_year_id = <year>`. A per-year list/breakdown uses **alive-in-year** scope (rule 2 + `reported_year_id`). **Do NOT use the all-years latest-phase dedup CTE for a single-year question** — it collapses years and returns each code's latest (often 2025) phase.

### 4. Portfolio era tripwire
- **2022–2024** → `INIT-##` / `SGP-##` codes (`portfolio_id = 2`)
- **2025+** → `SP01–SP13` codes (`portfolio_id = 3`)

`SP01–SP13` (e.g. "Breeding for Tomorrow") have **zero** records before 2025. If a single-year answer mixes `SP##` and `INIT-##`, or shows `SP##` before 2025, **the year filter is missing — re-query.**

### 5. Geography "Africa" = country-tagged **OR** region-tagged (a UNION)
A result can be tagged to a **region** (`result_region`) and/or specific **countries** (`result_country`). "Africa" must capture **both**:
```sql
-- African UN-M49 region tags: 2=Africa, 202=Sub-Saharan, 11/14/15/17/18 = W/E/N/Middle/Southern Africa
result_id IN (SELECT result_id FROM result_region  WHERE is_active=1 AND region_id IN (2,202,11,14,15,17,18))
OR
result_id IN (SELECT rc.result_id FROM result_country rc JOIN clarisa_countries cc ON cc.id=rc.country_id
              WHERE rc.is_active=1 AND cc.iso_alpha_3 IN (<54 African ISO-3 codes>))
```
The country→region table (`clarisa_countries_regions`) is **EMPTY** — derive African countries from the ISO-3 list, not from it. The dashboard's "Region/Country" slicer is a CGIAR-region → country tree (ESA, WCA, North-Africa-part-of-CWANA); selecting regions cascades to their countries, so it behaves like this UNION. Same pattern applies to any region (Asia, LAC, …).

### 6. Two totals, two questions — never conflate
- **"How many in year X"** → alive-in-year: `…reported_year_id=X` → **2022=477, 2023=872, 2024=1,016, 2025=963** W1/W2 (+222 bilateral = **1,185** in 2025).
- **"All-years headline total"** → latest-phase dedup CTE → **1,852** (1,630 W1/W2 + 222 bilateral).

### 7. Funding source is a hard boundary
`source='Result'` (W1/W2 pooled) vs `source='API'` (W3/bilateral). Never silently mix; bilateral only exists from 2025.

### 8. Show your interpretation before you run
State, in one short block: result type · year(s) · funding · geography definition · IRL/other filters · how counted. Pause for the user to confirm whenever a dimension is ambiguous (geography definition, alive-in-year vs latest, type scope, pooled vs bilateral). Then run.

---
*Worked check (2024, Africa, IRL 7+, Innovation Developments): region-only=111, country-only=203, **comprehensive country-OR-region = 264**. Led by INIT-01 Accelerated Breeding — no SP codes (correct for 2024).*
