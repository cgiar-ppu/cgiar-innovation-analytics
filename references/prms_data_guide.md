# PRMS Data Guide for the Innovation Analytics Agent

**Purpose:** Authoritative, query-ready guide for answering user questions about CGIAR **innovation developments** and **innovation uses** from the PRMS database. Built and validated 2026-06-13 against the live 13-June DB dump and the two dashboard Excel exports (Innovation Developments: 1,630 rows; Innovation Use: 624 rows). Reconstruction fidelity: ~98-100% row recall, 93-100% on every reproducible field — well above target.

> Companion files in this folder: `prms_schema_reference.md` (full schema), `cgiar_terminology.md`, `innovation_framework.md`. This guide is the practical query layer on top of them.

---

## Section 1 — Database Overview

PRMS (Performance and Results Management System) is CGIAR's authoritative results-reporting database. It holds **~32,000 result rows (27,800 active)** across **199 tables**, spanning reporting years **2022–2025**.

- **Two portfolio eras** (`version.portfolio_id`): **2** = Initiatives era 2022–2024 (codes `INIT-XX`, `SGP-XX`); **3** = Programs & Accelerators era 2025+ (codes `SP01`…`SP13`). A query that ignores era mixes two different org structures.
- **Reporting cycle = phase-based.** Seven phases in two parallel chains:
  - Reporting chain: `1` (2022) → `3` (2023) → `4` (2024) → `6` (2025, active)
  - IPSR chain: `2` (2023) → `5` (2024) → `7` (2025, active)
- **11 result types** (active counts): Knowledge product 12,853; **Innovation development 4,413**; Capacity sharing 4,034; Other output 3,670; **Innovation use 982**; Complementary innovation 610; Policy change 537; Other outcome 460; **Innovation Package/IPSR 224**; Capacity change 26 (deprecated); Impact contribution 2.

The public Results Dashboard exports are **deduplicated to one row per logical result** and filtered to **Quality-Assessed, pooled-funded** results. This guide encodes exactly that logic.

---

## Section 2 — Key Tables for Innovation Queries

| Table | Rows | Use |
|-------|------|-----|
| `result` | 32,026 (27,811 active) | Central fact table. Every result anchored here. |
| `results_innovations_dev` | 4,869 | **Innovation development** detail. Join `results_id → result.id`. |
| `results_innovations_use` | 619 | **Innovation use** detail. Join `results_id → result.id`. |
| `results_innovations_use_measures` | — | Use quantities. Join `result_innovation_use_id`. |
| `result_innovation_package` | 256 | **IPSR / Innovation Package** package-level (PK = `result.id`). |
| `result_by_innovation_package` | 1,893 | IPSR component innovations (core/complementary). Join `result_innovation_package_id`. |
| `version` | 7 | Phase/year/portfolio. Join `result.version_id`. |
| `result_type`, `result_level`, `result_status` | 11/4/7 | Lookups for type/level/status. |
| `results_by_inititiative` (TYPO double-t) | 38,860 | result ↔ initiative/program. role 1=primary, 2=contributor. |
| `clarisa_initiatives` | 62 | `official_code` (INIT-XX / SP01…), `name`. |
| `results_center` | 46,449 | result ↔ center; flags `is_primary`, `is_leading_result`. |
| `clarisa_center` | 17 | center `code`. |
| `results_by_institution` | — | partners/actors; `institution_roles_id` (2=Partner, 1=Actor…). |
| `result_country` / `result_region` | 34,701 / 21,437 | geography. |
| `evidence` | 49,931 | up to 6 links + cross-cutting flags per result. |
| `gender_tag_level` | 3 | the SHARED lookup for ALL FIVE impact tags. |
| `clarisa_innovation_readiness_level` / `_use_levels` | 10 / 10 | IRL / IUL (0-9). |

**Use which tables for what:**
- *Innovation developments* → `result` (type_id=7) + `results_innovations_dev`.
- *Innovation uses* → `result` (type_id=2) + `results_innovations_use`.
- *Innovation packages / scaling* → `result` (type_id=10) + `result_innovation_package` + `result_by_innovation_package`.

**Keys:**
- `result.id` (PK) = phase-specific row key → **join all satellites on this**.
- `result.result_code` = stable logical key across phases → **dedup/count on this**.
- Satellite join columns: `results_id` (dev, use, KP) or `result_id` (capdev, policy, complementary, IPSR component).

---

## Section 3 — Field Mapping Guide (Excel column → DB source)

### Innovation Developments export (41 columns)
| Excel column | DB source |
|--------------|-----------|
| Result code | `result.result_code` |
| Year | `result.reported_year_id` (= selected phase year) |
| PDF link | built: `reporting.cgiar.org/reports/result-details/{result_code}?phase={version_id}` |
| Funding source | `result.source` ('Result'→"Pooled funding (W1/W2)") |
| Submitter | `clarisa_initiatives.official_code` via `results_by_inititiative` role=1 |
| Level | `result_level.name` (always "Output" for dev) |
| Type | `result_type.name` ("Innovation development") |
| Title / Description | `result.title` / `result.description` |
| Lead contact person | `result.lead_contact_person` (COALESCE `ad_users.display_name` via `lead_contact_person_id`) |
| Gender/Climate/Nutrition/Env/Poverty level | `result.*_tag_level_id` → **`gender_tag_level.description`** ("(0) Not targeted") |
| Is KRS / KRS link | `result.is_krs` / `result.krs_url` |
| Legacy ID | `result.legacy_id` |
| Contributing CGIAR reporting entities | `results_by_inititiative` role=2 → official_code (GROUP_CONCAT) |
| Result leader | `results_center.is_leading_result=1` → center code (or partner) |
| Contributing centers | `results_center.is_primary=0` → center code |
| TOC results | (empty — 2025 ToC nodes are CLARISA-API only) |
| Partners | `results_by_institution` role=2 → `clarisa_institutions.name` |
| Countries / CGIAR regions | `result_country`/`result_region` → CLARISA names |
| Linked results | `linked_result` → other result_codes |
| Short title | `results_innovations_dev.short_title` |
| Innovation characterization | `clarisa_innovation_characteristic.name` via `innovation_characterization_id` |
| Innovation nature | `clarisa_innovation_type.name` via `innovation_nature_id` (PK=`code`) |
| Is new variety? / number_of_varieties | `results_innovations_dev.is_new_variety` / `.number_of_varieties` |
| Developers / Collaborators / Acknowledgement | `results_innovations_dev.innovation_developers` / `_collaborators` / `_acknowledgement` |
| **Readiness level** | `clarisa_innovation_readiness_level.level` (the 0-9 INTEGER, not the name) |
| Evidences explanation | `results_innovations_dev.evidences_justification` |
| Evidence 1-3 | pivot `evidence` (is_active=1) by `ROW_NUMBER() OVER (PARTITION BY result_id ORDER BY id)` |

### Innovation Use export (34 columns) — UNION of type 2 + type 10
Shared columns map as above. Type-specific:
| Excel column | DB source |
|--------------|-----------|
| Use level (Innovation use rows) | `clarisa_innovation_use_levels.level` via `results_innovations_use.innovation_use_level_id` |
| Users by actor | `result_actors` → `actor_type.name` + counts (free-text bullets) |
| Users by institutions | `results_by_institution_type` → `clarisa_institution_types.name` + counts |
| Scaling ambition (IPSR) | `result_innovation_package.scaling_ambition_blurb` |
| Innovation components (IPSR) | `result_by_innovation_package` → component `result.title` + `ipsr_role` |
| Experts (IPSR) | `result_ip_expert` → institutions / expertises |
| Scaling Partners (IPSR) | `results_by_institution` roles 5/6 |
| Readiness level / Use level / Readiness score / Potential score (IPSR) | **COMPUTED** scaling-readiness metrics — NOT a simple column; fetch from dashboard/PowerBI (see §5) |

---

## Section 4 — Validated SQL Query Templates

> **All templates assume SQLite.** Apply `is_active=1` everywhere. The "QAed snapshot" CTE below is the canonical dedup-to-one-row-per-result_code pattern that matches the public dashboard exports.

### 4.0 The canonical "one QAed row per result_code" selector (reusable)
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),   -- Reporting chain (use IPSR chain (2,0),(5,1),(7,2) for type 10)
cand AS (
  SELECT r.*, o.o AS phord
  FROM result r JOIN ord o ON o.v = r.version_id
  WHERE r.result_type_id = :type      -- 7 dev, 2 use, 10 IPSR
    AND r.source = 'Result'           -- W1/W2 pooled only
    AND r.is_active = 1
    AND r.status_id = 2               -- Quality Assessed
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (
  SELECT c.* FROM cand c JOIN pick p ON p.result_code=c.result_code AND p.m=c.phord
)
SELECT * FROM latest l
WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code);
```

### 4.1 Total count of innovation developments (dashboard-aligned)
```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand AS (SELECT r.result_code,o.o phord FROM result r JOIN ord o ON o.v=r.version_id
  WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2)
SELECT COUNT(DISTINCT result_code) FROM cand;   -- ~1,663 (dashboard shows 1,630)
```

### 4.2 Innovation developments by readiness level (IRL distribution)
```sql
SELECT cirl.level AS irl, cirl.name, COUNT(DISTINCT r.result_code) AS n
FROM result r
JOIN results_innovations_dev d ON d.results_id = r.id
JOIN clarisa_innovation_readiness_level cirl ON cirl.id = d.innovation_readiness_level_id
WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY cirl.level, cirl.name ORDER BY cirl.level;
```

### 4.3 Innovation developments by program/initiative (Submitter)
```sql
SELECT ci.official_code, ci.name, COUNT(DISTINCT r.result_code) AS n
FROM result r
JOIN results_by_inititiative rbi ON rbi.result_id=r.id AND rbi.initiative_role_id=1 AND rbi.is_active=1
JOIN clarisa_initiatives ci ON ci.id=rbi.inititiative_id
WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY ci.official_code, ci.name ORDER BY n DESC;
```

### 4.4 Innovation developments by year (dedup CTE required — simple GROUP BY is WRONG)

> ⚠️ **Common mistake:** `COUNT(DISTINCT result_code) ... GROUP BY reported_year_id` WITHOUT the dedup CTE returns **inflated counts** (e.g. 2024 returns 1,016 instead of ~445–488 depending on which DB snapshot is loaded — see annotation below). Why: a result_code carried forward from phase 4 (2024) into phase 6 (2025) has one row with `reported_year_id=2024` AND another with `reported_year_id=2025` — so a naive GROUP BY counts it in BOTH years. The correct approach: apply the dedup CTE first (one canonical row per result_code), THEN group by `reported_year_id` of that canonical row. "2024 innovations" = result_codes whose LATEST active phase is Reporting 2024.

```sql
WITH ord(v,o) AS (VALUES (1,0),(3,1),(4,2),(6,3)),
cand AS (
  SELECT r.result_code, r.reported_year_id, r.id, o.o AS phord
  FROM result r JOIN ord o ON o.v = r.version_id
  WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
),
pick AS (SELECT result_code, MAX(phord) AS m FROM cand GROUP BY result_code),
latest AS (
  SELECT c.* FROM cand c JOIN pick p ON p.result_code=c.result_code AND p.m=c.phord
),
deduped AS (
  SELECT l.result_code, l.reported_year_id
  FROM latest l WHERE l.id = (SELECT MAX(l2.id) FROM latest l2 WHERE l2.result_code = l.result_code)
)
SELECT reported_year_id AS year, COUNT(*) AS n
FROM deduped
GROUP BY reported_year_id ORDER BY year;
-- CORRECT (dedup CTE — exact integers are snapshot-dependent):
--   prdb_fresh.sqlite (June 13 2026 mysqldump, dashboard-exact):  2022:83  2023:172  2024:445  2025:963
--   prdb.sqlite       (live server, ~Mar 2026 snapshot):           2022:83  2023:172  2024:488  2025:902
-- What matters is using the dedup CTE — NOT a naive WHERE reported_year_id filter.
-- DO NOT use simple GROUP BY reported_year_id without the CTE — inflated: 2022:477, 2023:872, 2024:1016, 2025:963
```

### 4.5 Geographic distribution of innovation developments
```sql
SELECT cc.name AS country, COUNT(DISTINCT r.result_code) AS n
FROM result r
JOIN result_country rc ON rc.result_id=r.id AND rc.is_active=1
JOIN clarisa_countries cc ON cc.id=rc.country_id
WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY cc.name ORDER BY n DESC LIMIT 20;
```

### 4.6 Innovation uses by use level (IUL)
```sql
SELECT ciu.level AS iul, ciu.name, COUNT(DISTINCT r.result_code) AS n
FROM result r
JOIN results_innovations_use u ON u.results_id=r.id
JOIN clarisa_innovation_use_levels ciu ON ciu.id=u.innovation_use_level_id
WHERE r.result_type_id=2 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY ciu.level, ciu.name ORDER BY ciu.level;
```

### 4.7 Innovation developments by characterization / nature (typology)
```sql
SELECT chc.name AS characterization, it.name AS nature, COUNT(DISTINCT r.result_code) AS n
FROM result r
JOIN results_innovations_dev d ON d.results_id=r.id
LEFT JOIN clarisa_innovation_characteristic chc ON chc.id=d.innovation_characterization_id
LEFT JOIN clarisa_innovation_type it ON it.code=d.innovation_nature_id
WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY chc.name, it.name ORDER BY n DESC;
```

### 4.8 Impact-area tag breakdown (e.g. gender) for innovation developments
```sql
SELECT gtl.description AS gender_tag, COUNT(DISTINCT r.result_code) AS n
FROM result r LEFT JOIN gender_tag_level gtl ON gtl.id=r.gender_tag_level_id
WHERE r.result_type_id=7 AND r.source='Result' AND r.is_active=1 AND r.status_id=2
GROUP BY gtl.description;   -- swap gender_tag_level_id for climate_change_tag_level_id etc.
```

### 4.9 Innovation packages (IPSR) list with scaling ambition
```sql
WITH iord(v,o) AS (VALUES (2,0),(5,1),(7,2)),
cand AS (SELECT r.id,r.result_code,r.title,o.o phord FROM result r JOIN iord o ON o.v=r.version_id
  WHERE r.result_type_id=10 AND r.source='Result' AND r.is_active=1 AND r.status_id=2),
pick AS (SELECT result_code,MAX(phord) m FROM cand GROUP BY result_code)
SELECT c.result_code, c.title, ip.scaling_ambition_blurb
FROM cand c JOIN pick p ON p.result_code=c.result_code AND p.m=c.phord
JOIN result_innovation_package ip ON ip.result_innovation_package_id=c.id;
```

### 4.10 Cross-phase trace of one logical result
```sql
SELECT r.id, r.result_code, v.phase_name, r.is_replicated, r.status_id, r.reported_year_id
FROM result r JOIN version v ON v.id=r.version_id
WHERE r.result_code = :code AND r.is_active=1
ORDER BY v.phase_year;
```

---

## Section 5 — Business Rules & Gotchas

1. **Dashboard-aligned counts use the QAed snapshot**: `source='Result' AND is_active=1 AND status_id=2`, deduped to one row per `result_code` (latest phase in its chain). This is the single most important rule for matching official figures.
2. **`status_id=2` = "Quality Assessed"** is the de-facto "published to dashboard" gate. (A ~2% residual over-inclusion vs the live dashboard comes from a manually-refreshed semantic-model gate that can't be fully reproduced from stored fields — surface it as a caveat, not an error.)
3. **Funding source filter**: `result.source='Result'` = W1/W2 pooled; `='API'` = W3/Bilateral. The two exports are W1/W2 ONLY. NEVER silently mix W3/bilateral — it follows a different QA pathway and carries a disclaimer requirement.
4. **Join satellites on `result.id`, dedup/count on `result_code`.** Mixing them double-counts or returns wrong-phase data.
5. **Readiness level / Use level in the exports are the 0-9 INTEGER** (`clarisa_*.level`), not the descriptive name.
6. **Impact-area tag text** comes from `gender_tag_level.description` ("(0) Not targeted" / "(1) Significant" / "(2) Principal"), and all five impact dimensions share that one lookup table.
7. **Climate tags are systematically under-applied** — never treat `climate_change_tag_level_id > 1` as a complete census of climate-relevant innovations; add a caveat or AI-inferred relevance (clearly labelled).
8. **IPSR scaling scores (Readiness/Use level, Readiness/Potential score) are computed**, not stored as a single column — fetch from the dashboard / PowerBI dataflow if a user needs them.
9. **`TOC results` and 2025 ToC indicator names are CLARISA-API only** — not in the local DB. Don't fabricate them.
10. **Preserve schema typos** in SQL: `results_by_inititiative`, `inititiative_id` (double-t), `accesible`, `readinees_evidence_link`, `result-country` (hyphen), `non_pooled_projetct_budget`, `is_not_aplicable`, `toc_pahse_id`.
11. **Multi-valued fields** (centers, partners, countries, contributing entities, evidence) are GROUP_CONCAT'd per result — handle one-to-many with sub-queries, never a naive JOIN that multiplies rows.
12. **PDF-link decoding**: `result-details/{result_code}?phase={version_id}` (or `ipsr-details/...`) tells you exactly which phase-version a dashboard row reflects.

---

## Section 6 — Naming Conventions (user phrasing → data)

| User says | Means in PRMS |
|-----------|---------------|
| "innovation" (generic) | usually result_type 7 (Innovation development); sometimes 2 (use) or 10 (package) — clarify |
| "innovation use / uptake / adoption" | result_type 2 (Innovation use); `Use level` = IUL |
| "readiness / scaling readiness / TRL" | IRL via `clarisa_innovation_readiness_level` (0-9) on innovation dev / IPSR |
| "use level / IUL" | `clarisa_innovation_use_levels` (0-9) |
| "innovation package / IPSR / scaling readiness assessment" | result_type 10 + `result_innovation_package` |
| "program / initiative / who reported it / submitter" | `clarisa_initiatives.official_code` via `results_by_inititiative` role=1 |
| "center / lead center / result leader" | `results_center` (is_leading_result / is_primary) → `clarisa_center.code` |
| "partners" | `results_by_institution` role=2 → `clarisa_institutions.name` |
| "actors / users / beneficiaries" | `result_actors` / `results_by_institution_type` (Users by actor / institutions) |
| "this year / 2025 / latest cycle" | phase 6 (Reporting 2025) / phase 7 (IPSR 2025); `reported_year_id` |
| "W1/W2 / pooled" vs "W3 / bilateral" | `result.source` = 'Result' vs 'API' |
| "QAed / quality assured / official" | `result.status_id = 2` |
| "variety / breed" | `results_innovations_dev.is_new_variety` / `number_of_varieties` |
| "evidence" | `evidence` table (up to 6 links/result) |

---

## Section 7 — Open Questions

1. **The exact dashboard publication gate** beyond `status_id=2` that excludes ~33 dev / 2 use historical result_codes (manually-refreshed `CGIAR_result_dashboard` semantic model is the leading suspect; confirm with Manuel Ricardo Almanzar).
2. **IPSR computed scores** (Readiness/Use level, Readiness/Potential score) — the exact derivation formula from `result_by_innovation_package` component levels is not stored; needs the IPSR Step-3 Assess calculation (Marc Schut / PRMS dev).
3. **Lead contact person** ~7% value drift — whether the export uses a specific phase-version's contact or a different name-resolution order.
4. **`status_id=2` vs `in_qa`/`6 Approved`** for W3/bilateral results — bilateral statuses are pending/approved/rejected (show only approved); this guide covers W1/W2 only.
5. **2024 vs 2025 IRL/IUL carry-forward** — replicated results may carry unchanged prior-year readiness/use values (known data-quality flag); treat identical adjacent-phase IRL/IUL with caution.
