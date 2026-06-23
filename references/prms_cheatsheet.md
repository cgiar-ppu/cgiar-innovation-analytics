# PRMS Cheat Sheet — the 8 rules that prevent 90% of wrong answers

**Read this first. It is short on purpose.** Deeper detail lives in `prms_query_cookbook` and `prms_data_guide`; this page is the always-on muscle memory.

---

### 1. Count innovations by `result_code`, never by `id` or rows
The same innovation gets a new `result.id` every year but keeps its `result_code`. → `COUNT(DISTINCT result_code)`.

### 2. Default filter for innovation queries — include BOTH funding windows, broken out
```sql
result_type_id = 7 AND is_active = 1
-- DEFAULT = W1/W2 pooled + W3/bilateral, presented broken out (W1/W2 / bilateral / Total):
AND (
     (source = 'Result' AND status_id = 2)   -- W1/W2 pooled (public dashboard); "Quality Assessed" (~2% residual expected)
  OR (source = 'API'    AND status_id = 6)   -- W3/bilateral; "Approved" QA gate; not on public dashboard; 2025+ only
)
```
Always split W1/W2 vs W3/bilateral in the output (a labelled row/series), never blend into one number. For the **pooled-only / public-dashboard view** (on request), keep only the `source='Result' AND status_id=2` arm.

**"QAed" = two gates, one per window.** Quality assurance runs separately for each funding window: W1/W2 → `status_id=2` ("Quality Assessed"); W3/bilateral → `status_id=6` ("Approved", a separate process + reviewers via the CLARISA API). Bilateral results are fully quality-assured — they just don't carry `status_id=2`. So "QAed results" and any unqualified "results"/"innovations" request includes BOTH; **never require `status_id=2` of bilateral rows.**

### 3. Year: if a year is in play, FILTER by it
If the user names a year — now or in an earlier turn (it **carries forward**) — your SQL **must** contain `reported_year_id = <year>`. A per-year list/breakdown uses **alive-in-year** scope (rule 2 + `reported_year_id`). **Do NOT use the all-years latest-phase dedup CTE for a single-year question** — it collapses years and returns each code's latest (often 2025) phase.

### 4. Portfolio era tripwire
- **2022–2024** → `INIT-##` / `SGP-##` codes (`portfolio_id = 2`)
- **2025+** → `SP01–SP13` codes (`portfolio_id = 3`)

`SP01–SP13` (e.g. "Breeding for Tomorrow") have **zero** records before 2025. If a single-year answer mixes `SP##` and `INIT-##`, or shows `SP##` before 2025, **the year filter is missing — re-query.**

**Name-level tripwire:** the *names* are era-bound too. "Breeding for Tomorrow" (SP01), "Sustainable Farming" (SP02), "Scaling for Impact" (SP09), "Digital Transformation" (SP12) and the other SP01–SP13 Science-Program names belong to 2025+ ONLY. Their 2022–2024 equivalents are Initiative names (e.g. "Accelerated Breeding" = INIT-01, "Plant Health" = INIT-13). If an SP Science-Program NAME (not just the code) appears in a pre-2025 answer, or an SP name is presented as a 2024 finding, the year filter is missing — re-query. Never treat an SP## name and its INIT## predecessor as interchangeable within one year's answer.

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
- **"How many in year X"** → alive-in-year: `…reported_year_id=X` → default **Totals 2022=477, 2023=872, 2024=1,016, 2025=1,185** (2025 = 963 W1/W2 + 222 bilateral; bilateral is 0 for 2022–2024). Show the W1/W2 + bilateral split.
- **"All-years headline total"** → latest-phase dedup CTE (W1/W2) + bilateral arm → **1,852** (1,630 W1/W2 + 222 bilateral).

### 7. Funding source — include both by default, but keep them labelled
`source='Result' AND status_id=2` (W1/W2 pooled) and `source='API' AND status_id=6` (W3/bilateral). **Default = include both, presented broken out** (W1/W2 / bilateral / Total). Never *silently blend* them into one undifferentiated figure, and never drop bilateral unless the user asks for the pooled-only / public-dashboard view. Bilateral only exists from 2025.

### 8. Show your interpretation before you run
State, in one short block: result type · year(s) · funding · geography definition · IRL/other filters · how counted. Pause for the user to confirm whenever a dimension is ambiguous (geography definition, alive-in-year vs latest, type scope, pooled vs bilateral). Then run.

### 9. Innovation Packages (type 10): DISTINCT, year-matched, and caveated
Linking innovations (type 7) to packages (type 10) via `result_by_innovation_package` FANS OUT (one innovation → many packages; membership repeats across phases). Always count with `COUNT(DISTINCT result_code)` / `COUNT(DISTINCT package_code)`, keep the component population in the SAME year/era as the question, and remember the type-10 count is an OPEN item — caveat any "% packaged" figure. (164 type-10 QAed rows / 74 codes DO satisfy `source='Result' AND status_id=2`; the all-years dedup CTE nonetheless returns 0 for type 10 because its `ord(v,o)` phase map covers `version_id` ∈ {1,3,4,6} while type-10 QAed rows live on {2,5,7} — see OI-3 / `prms_data_guide` §11.3. The naive `is_active=1` count gives 96 vs 223 raw.)

---
*Worked check (2024, Africa, IRL 7+, Innovation Developments): region-only=111, country-only=203, **comprehensive country-OR-region = 264**. Led by INIT-01 Accelerated Breeding — no SP codes (correct for 2024).*
