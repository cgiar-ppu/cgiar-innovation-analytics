# PRMS Database Schema Reference

**Database:** `/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite` (SQLite 3.x, ~398 MB)
**Snapshot date:** 2026-03-18 (from AWS RDS MySQL `prmsdb`)
**Total tables:** 197 | **Active results:** ~27,803 (is_active=1 in `result`)

---

## Core Concepts

PRMS (Performance and Results Management System) tracks CGIAR research outputs and outcomes. The central entity is a **result** -- a research output, innovation, knowledge product, policy change, or capacity development activity. Results are linked to CGIAR **initiatives** (programmes), **institutions** (partners), **countries/regions** (geography), and typed by **result_type** and **result_level**.

**Key foreign key patterns:**
- `result.result_type_id` -> `result_type.id`
- `result.result_level_id` -> `result_level.id`
- `result.geographic_scope_id` -> `clarisa_geographic_scope.id`
- `result.status_id` -> `result_status.result_status_id`
- Junction tables use `result_id` to link results to other entities

**Soft-delete pattern:** Most tables have `is_active` (tinyint, 0/1). Always filter `WHERE is_active = 1` unless analyzing deleted records.

**Reporting years:** Results have `reported_year_id` (values: 2022, 2023, 2024, 2025 -- note 610 rows have NULL year).

---

## 1. Result (Core Table)

### `result` (32,005 rows)
The central entity table. Every CGIAR output/outcome is a row here.

| Column | Type | Description |
|--------|------|-------------|
| `id` | bigint PK | Unique result identifier |
| `title` | TEXT | Result title/name |
| `description` | TEXT | Full description (often NULL for knowledge products) |
| `result_code` | bigint | Sequential code |
| `result_type_id` | INT | FK -> result_type.id (1-11) |
| `result_level_id` | INT | FK -> result_level.id (1-4) |
| `is_active` | tinyint | 1=active, 0=deleted |
| `reported_year_id` | year | Reporting year (2022-2025) |
| `geographic_scope_id` | INT | FK -> clarisa_geographic_scope.id |
| `has_regions` | tinyint | Whether result has region assignments |
| `has_countries` | tinyint | Whether result has country assignments |
| `status_id` | bigint | FK -> result_status.result_status_id |
| `gender_tag_level_id` | bigint | FK -> gender_tag_level.id (1-3) |
| `climate_change_tag_level_id` | bigint | Cross-cutting tag |
| `nutrition_tag_level_id` | bigint | Cross-cutting tag |
| `environmental_biodiversity_tag_level_id` | bigint | Cross-cutting tag |
| `poverty_tag_level_id` | bigint | Cross-cutting tag |
| `created_date` | timestamp | When the result was created |
| `last_updated_date` | timestamp | Last modification |
| `created_by` | INT | User who created |
| `is_discontinued` | tinyint | Discontinued flag |
| `lead_contact_person` | TEXT | Contact person name |
| `krs_url` | TEXT | Key Result Story URL |
| `source` | TEXT | Usually 'Result' |

---

## 2. Lookup/Reference Tables

### `result_type` (11 rows)
| id | name | Active result count |
|----|------|-------------------|
| 1 | Policy change | 537 |
| 2 | Innovation use | 976 |
| 3 | Capacity change | 26 |
| 4 | Other outcome | 460 |
| 5 | Capacity sharing for development | 4,033 |
| 6 | Knowledge product | 12,850 |
| 7 | Innovation development | 4,416 |
| 8 | Other output | 3,670 |
| 9 | Impact contribution | 2 |
| 10 | Innovation Package | 223 |
| 11 | Complementary innovation | 610 |

### `result_level` (4 rows)
| id | name | description |
|----|------|-------------|
| 1 | Impact | Durable change in conditions |
| 2 | Action Area outcome | Change in knowledge/attitudes/skills |
| 3 | Outcome | Change in behavior from research |
| 4 | Output | Knowledge or technical advancement |

### `result_status` (7 rows)
| result_status_id | status_name |
|-------------------|-------------|
| 1 | Editing |
| 2 | Quality Assessed |
| 3 | Submitted |
| 4 | Discontinued |
| 5 | Pending Review |
| 6 | Approved |
| 7 | Rejected |

### `clarisa_geographic_scope` (6 rows)
| id | name |
|----|------|
| 1 | Global |
| 2 | Regional |
| 3 | Multi-national |
| 4 | National |
| 5 | Sub-national |
| 50 | This is yet to be determined |

### `gender_tag_level` (3 rows)
| id | title |
|----|-------|
| 1 | Not targeted |
| 2 | Significant |
| 3 | Principal |

---

## 3. Initiative/Programme Tables

### `clarisa_initiatives` (62 rows)
CGIAR Initiatives (programmes/projects).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Unique identifier |
| `official_code` | TEXT | Code like INIT-01, SGP-03 |
| `name` | TEXT | Full initiative name |
| `short_name` | TEXT | Short display name |
| `active` | tinyint | Active flag |

### `results_by_inititiative` (38,839 rows)
**Junction table** linking results to initiatives. NOTE: table name has typo ("inititiative").

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `inititiative_id` | INT | FK -> clarisa_initiatives.id (NOTE: typo in column name) |
| `initiative_role_id` | bigint | 1=lead, other=contributing |
| `is_active` | tinyint | Active flag |

**Common join:**
```sql
SELECT ci.short_name, COUNT(DISTINCT rbi.result_id) as result_count
FROM results_by_inititiative rbi
JOIN clarisa_initiatives ci ON rbi.inititiative_id = ci.id
JOIN result r ON rbi.result_id = r.id
WHERE rbi.is_active = 1 AND r.is_active = 1
GROUP BY ci.short_name
ORDER BY result_count DESC;
```

---

## 4. Geography Tables

### `clarisa_countries` (249 rows)
| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Country ID |
| `name` | TEXT | Country name (English, sometimes formal e.g. "Tanzania, United Republic") |
| `iso_alpha_3` | TEXT | ISO 3166-1 alpha-3 code |
| `iso_alpha_2` | varchar(5) | ISO 3166-1 alpha-2 code |

### `result_country` (34,479 rows)
**Junction table** linking results to countries.

| Column | Type | Description |
|--------|------|-------------|
| `result_country_id` | bigint PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `country_id` | INT | FK -> clarisa_countries.id |
| `is_active` | tinyint | Active flag |
| `geo_scope_role_id` | INT | 1=primary, 2=additional |

**Common join (top countries):**
```sql
SELECT cc.name, COUNT(DISTINCT rc.result_id) as result_count
FROM result_country rc
JOIN clarisa_countries cc ON rc.country_id = cc.id
JOIN result r ON rc.result_id = r.id
WHERE rc.is_active = 1 AND r.is_active = 1
GROUP BY cc.name
ORDER BY result_count DESC LIMIT 10;
```

### `clarisa_regions` (31 rows)
UN M49 regions hierarchy.

| Column | Type | Description |
|--------|------|-------------|
| `um49Code` | INT PK | UN M49 region code |
| `name` | TEXT | Region name (e.g. "Eastern Africa", "Southern Asia") |
| `parent_regions_code` | INT | FK to parent region (self-referential hierarchy) |

Key regions: Africa (2), Americas (19), Asia (142), Europe (150), Oceania (9), Sub-Saharan Africa (202), Latin America and the Caribbean (419).

### `result_region` (21,406 rows)
**Junction table** linking results to regions.

| Column | Type | Description |
|--------|------|-------------|
| `result_region_id` | bigint PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `region_id` | INT | FK -> clarisa_regions.um49Code |
| `is_active` | tinyint | Active flag |
| `geo_scope_role_id` | INT | 1=primary, 2=additional |

### `clarisa_subnational_scopes` (5,020 rows)
Sub-national administrative areas for fine-grained geography.

### `result_country_subnational` (2,058 rows)
Links results to sub-national areas.

---

## 5. Institution/Partner Tables

### `clarisa_institutions` (10,579 rows)
Master list of all institutions (CGIAR centers, universities, NGOs, government bodies, private sector).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Institution ID |
| `name` | TEXT | Full institution name |
| `acronym` | TEXT | Abbreviation (e.g. IRRI, CIMMYT) |
| `website_link` | TEXT | URL |
| `institution_type_code` | INT | FK to clarisa_institution_types |
| `headquarter_country_iso2` | varchar(5) | HQ country ISO-2 |

### `clarisa_center` (17 rows)
CGIAR research centers specifically.

| code | acronym | name |
|------|---------|------|
| CENTER-01 | AfricaRice | Africa Rice Center |
| CENTER-02 | ABC | Alliance of Bioversity and CIAT - HQ |
| CENTER-03 | ABC RH | Alliance of Bioversity and CIAT - Regional Hub |
| CENTER-04 | CIFOR | Center for International Forestry Research |
| CENTER-05 | CIMMYT | International Maize and Wheat Improvement Center |
| CENTER-06 | CIP | International Potato Center |
| CENTER-07 | ICARDA | Intl Center for Agricultural Research in Dry Areas |
| CENTER-08 | ICRAF | World Agroforestry Centre |
| CENTER-09 | ICRISAT | Intl Crops Research Institute for Semi-Arid Tropics |
| CENTER-10 | IFPRI | International Food Policy Research Institute |
| CENTER-11 | IITA | International Institute of Tropical Agriculture |
| CENTER-12 | ILRI | International Livestock Research Institute |
| CENTER-13 | IRRI | International Rice Research Institute |
| CENTER-14 | IWMI | International Water Management Institute |
| CENTER-15 | WorldFish | WorldFish |
| CENTER-16 | SO | CGIAR System Organization |

### `results_by_institution` (78,345 rows)
**Junction table** linking results to institutions (partners).

| Column | Type | Description |
|--------|------|-------------|
| `id` | bigint PK | Row ID |
| `institutions_id` | INT | FK -> clarisa_institutions.id |
| `institution_roles_id` | bigint | FK -> institution_role.id |
| `result_id` | bigint | FK -> result.id |
| `is_active` | tinyint | Active flag |
| `is_leading_result` | tinyint | Whether this institution leads the result |

### `institution_role` (8 rows)
| id | name |
|----|------|
| 1 | Actor |
| 2 | Partner |
| 3 | Capdev trainees on behalf |
| 4 | Policy owner |
| 5 | Innovation Package Partners |
| 6 | Core Innovation Package Partners |
| 7 | Expected partner |
| 8 | Knowledge Product Additional Contributors |

### `results_center` (46,300 rows)
Links results to CGIAR centers specifically.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `center_id` | varchar(15) | FK -> clarisa_center.code |
| `is_primary` | tinyint | 1=primary center |
| `is_active` | tinyint | Active flag |
| `is_leading_result` | tinyint | Whether center leads this result |

**Common join (results by center):**
```sql
SELECT cc.code, ci.acronym, COUNT(DISTINCT rc2.result_id) as result_count
FROM results_center rc2
JOIN clarisa_center cc ON rc2.center_id = cc.code
JOIN clarisa_institutions ci ON cc.institutionId = ci.id
JOIN result r ON rc2.result_id = r.id
WHERE rc2.is_active = 1 AND r.is_active = 1
GROUP BY cc.code, ci.acronym
ORDER BY result_count DESC;
```

---

## 6. Innovation Tables

### `results_innovations_dev` (4,867 rows)
Details for result_type_id=7 (Innovation development).

| Column | Type | Description |
|--------|------|-------------|
| `result_innovation_dev_id` | INT PK | Row ID |
| `results_id` | bigint | FK -> result.id |
| `short_title` | TEXT | Innovation short title |
| `innovation_readiness_level_id` | INT | FK -> clarisa_innovation_readiness_level.id |
| `innovation_characterization_id` | INT | FK -> clarisa_innovation_characteristic.id |
| `innovation_nature_id` | INT | FK -> clarisa_innovation_type.code |
| `is_new_variety` | tinyint | Crop variety flag |
| `number_of_varieties` | bigint | Number of varieties if applicable |
| `innovation_developers` | TEXT | Developer names/contacts |
| `innovation_collaborators` | TEXT | Collaborator details |
| `readiness_level` | TEXT | Deprecated text field for readiness |
| `evidences_justification` | TEXT | Justification text |
| `is_active` | tinyint | Active flag |

### `clarisa_innovation_readiness_level` (10 rows)
| id | name | level |
|----|------|-------|
| 11 | Idea | 0 |
| 12 | Basic Research | 1 |
| 13 | Formulation | 2 |
| 14 | Proof of Concept | 3 |
| 15 | Controlled Testing | 4 |
| 16 | Model/Early Prototype | 5 |
| 17 | Semi-Controlled Testing | 6 |
| 18 | Prototype | 7 |
| 19 | Uncontrolled Testing | 8 |
| 20 | Proven Innovation | 9 |

**Common join (innovations by readiness level):**
```sql
SELECT cirl.level, cirl.name, COUNT(*) as cnt
FROM results_innovations_dev rid
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
JOIN result r ON rid.results_id = r.id
WHERE rid.is_active = 1 AND r.is_active = 1
GROUP BY cirl.level, cirl.name
ORDER BY cirl.level;
```

### `clarisa_innovation_type` (4 rows)
| code | name |
|------|------|
| 12 | Technological innovation |
| 13 | Capacity development innovation |
| 14 | Policy, organizational or institutional innovation |
| 15 | Other/I'm not sure |

### `clarisa_innovation_characteristic` (4 rows)
| id | name |
|----|------|
| 1 | Incremental innovation |
| 2 | Radical innovation |
| 3 | Disruptive innovation |
| 4 | Other |

### `results_innovations_use` (599 rows)
Details for result_type_id=2 (Innovation use/adoption).

| Column | Type | Description |
|--------|------|-------------|
| `result_innovation_use_id` | INT PK | Row ID |
| `results_id` | bigint | FK -> result.id |
| `male_using` | bigint | Male users count |
| `female_using` | bigint | Female users count |
| `innovation_use_level_id` | bigint | FK -> clarisa_innovation_use_levels.id |
| `is_active` | tinyint | Active flag |

### `clarisa_innovation_use_levels` (10 rows)
Levels 0-9 describing adoption from "No use" to "Commonly used by end-users/beneficiaries".

### `result_actors` (8,128 rows)
Actors (users) of innovations with demographic breakdowns.

| Column | Type | Description |
|--------|------|-------------|
| `result_actors_id` | bigint PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `actor_type_id` | bigint | FK -> actor_type.actor_type_id |
| `women` | bigint | Female count |
| `men` | bigint | Male count |
| `women_youth` | bigint | Female youth count |
| `men_youth` | bigint | Male youth count |
| `how_many` | bigint | Total count |
| `other_actor_type` | TEXT | Description if actor_type_id=5 |
| `sex_and_age_disaggregation` | tinyint | Whether disaggregation is available |

### `actor_type` (5 rows)
| actor_type_id | name |
|---------------|------|
| 1 | Farmers/ (agro)pastoralist/ herders/ fishers |
| 2 | Researchers |
| 3 | Agricultural extension agents |
| 4 | Policy actors (public or private) |
| 5 | Other |

---

## 7. Knowledge Product Tables

### `results_knowledge_product` (13,755 rows)
Details for result_type_id=6 (Knowledge products -- publications, datasets, etc).

| Column | Type | Description |
|--------|------|-------------|
| `result_knowledge_product_id` | bigint PK | Row ID |
| `results_id` | bigint | FK -> result.id |
| `handle` | TEXT | Handle.net identifier (e.g. "10568/125543") |
| `doi` | TEXT | DOI URL |
| `name` | TEXT | Product name |
| `description` | TEXT | Product description |
| `knowledge_product_type` | TEXT | Type classification |
| `licence` | TEXT | License info |
| `comodity` | TEXT | Related commodity |
| `sponsors` | TEXT | Sponsors/funders |
| `findable` | float | FAIR score - Findable |
| `accesible` | float | FAIR score - Accessible |
| `interoperable` | float | FAIR score - Interoperable |
| `reusable` | float | FAIR score - Reusable |
| `is_melia` | tinyint | Monitoring/evaluation flag |

### `results_kp_metadata` (19,176 rows)
Extended metadata for knowledge products (authors, journal, publication date, etc).

### `results_kp_authors` (77,384 rows)
Author records linked to knowledge products.

### `results_kp_altmetrics` (13,718 rows)
Altmetric scores for knowledge products.

---

## 8. Capacity Development Tables

### `results_capacity_developments` (4,411 rows)
Details for result_type_id=5 (Capacity sharing for development).

| Column | Type | Description |
|--------|------|-------------|
| `result_capacity_development_id` | INT PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `male_using` | bigint | Male trainees |
| `female_using` | bigint | Female trainees |
| `non_binary_using` | bigint | Non-binary trainees |
| `has_unkown_using` | bigint | Unknown gender count |
| `capdev_delivery_method_id` | INT | FK -> capdevs_delivery_methods.capdev_delivery_method_id |
| `capdev_term_id` | INT | FK -> capdevs_term.capdev_term_id |
| `is_active` | tinyint | Active flag |

### `capdevs_term` (4 rows)
| capdev_term_id | name | term |
|----------------|------|------|
| 1 | PhD | Long-term |
| 2 | Master | Long-term |
| 3 | Short-term | Short-term |
| 4 | Long-term | Long-term |

### `capdevs_delivery_methods` (3 rows)
| capdev_delivery_method_id | name |
|---------------------------|------|
| 1 | Virtual / Online |
| 2 | In person |
| 3 | Blended (in-person and virtual) |

---

## 9. Policy Change Tables

### `results_policy_changes` (572 rows)
Details for result_type_id=1 (Policy change).

| Column | Type | Description |
|--------|------|-------------|
| `result_policy_change_id` | INT PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `policy_stage_id` | INT | FK -> clarisa_policy_stage.id |
| `policy_type_id` | INT | FK -> clarisa_policy_type.id |
| `amount` | float | Budget amount (for investment type) |
| `is_active` | tinyint | Active flag |

### `clarisa_policy_stage` (3 rows)
| id | name | definition |
|----|------|------------|
| 6 | Stage 1 | Research taken up by next user |
| 7 | Stage 2 | Policy enacted |
| 8 | Stage 3 | Evidence of impact of policy |

### `clarisa_policy_type` (3 rows)
| id | name |
|----|------|
| 1 | Program, budget or investment |
| 2 | Legal instrument |
| 3 | Policy or strategy |

---

## 10. Evidence & Links

### `evidence` (49,784 rows)
Evidence links attached to results.

| Column | Type | Description |
|--------|------|-------------|
| `id` | bigint PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `link` | TEXT | URL of evidence |
| `description` | TEXT | Description of evidence |
| `is_active` | tinyint | Active flag |
| `gender_related` | tinyint | Cross-cutting tag |
| `youth_related` | tinyint | Cross-cutting tag |
| `is_supplementary` | tinyint | Supplementary evidence flag |

### `linked_result` (14,125 rows)
Cross-references between results.

| Column | Type | Description |
|--------|------|-------------|
| `id` | bigint PK | Row ID |
| `linked_results_id` | bigint | FK -> result.id (target) |
| `origin_result_id` | bigint | FK -> result.id (source) |
| `is_active` | tinyint | Active flag |

---

## 11. Project/Funding Tables

### `results_by_projects` (2,154 rows)
Links results to bilateral/W3 projects.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT PK | Row ID |
| `result_id` | bigint | FK -> result.id |
| `project_id` | bigint | FK -> clarisa_projects.id |
| `is_lead` | tinyint | Lead project flag |
| `is_active` | tinyint | Active flag |

### `clarisa_projects` (299 rows)
Bilateral and W3 project master data.

### `result_initiative_budget` (28,809 rows)
Budget allocations per result per initiative.

---

## 12. TOC (Theory of Change) Tables

### `toc_result` (53,579 rows)
Theory of Change result entries -- expected outputs/outcomes per initiative.

### `results_toc_result` (41,075 rows)
Links actual results to TOC entries (maps what was achieved to what was planned).

### `results_toc_result_indicators` (33,783 rows)
Links results to specific TOC indicators.

---

## 13. SDG Tables

### `clarisa_sdgs` (17 unique SDGs, 52,360 rows due to duplicates)
Sustainable Development Goals. Use DISTINCT or LIMIT to usnd_code <= 17.

| Column | Type | Description |
|--------|------|-------------|
| `usnd_code` | bigint PK | SDG number (1-17) |
| `short_name` | varchar(100) | e.g. "Goal 2: Zero Hunger" |
| `full_name` | varchar(400) | Full description |

### `result_sdg_targets` (1 row -- mostly unused)
### `result_toc_sdg_targets` (227,051 rows)
Maps results to SDG targets via TOC.

---

## Common Query Patterns

### Count results by type
```sql
SELECT rt.name, COUNT(*) as count
FROM result r
JOIN result_type rt ON r.result_type_id = rt.id
WHERE r.is_active = 1
GROUP BY rt.name ORDER BY count DESC;
```

### Results by reporting year
```sql
SELECT reported_year_id, COUNT(*) as count
FROM result WHERE is_active = 1
GROUP BY reported_year_id ORDER BY reported_year_id;
```

### Top countries by result count
```sql
SELECT cc.name as country, cc.iso_alpha_2, COUNT(DISTINCT rc.result_id) as result_count
FROM result_country rc
JOIN clarisa_countries cc ON rc.country_id = cc.id
JOIN result r ON rc.result_id = r.id
WHERE rc.is_active = 1 AND r.is_active = 1
GROUP BY cc.name ORDER BY result_count DESC LIMIT 20;
```

### Results by initiative (programme)
```sql
SELECT ci.short_name as initiative, COUNT(DISTINCT rbi.result_id) as result_count
FROM results_by_inititiative rbi
JOIN clarisa_initiatives ci ON rbi.inititiative_id = ci.id
JOIN result r ON rbi.result_id = r.id
WHERE rbi.is_active = 1 AND r.is_active = 1
GROUP BY ci.short_name ORDER BY result_count DESC;
```

### Innovations by readiness level
```sql
SELECT cirl.level, cirl.name as readiness_level, COUNT(*) as count
FROM results_innovations_dev rid
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
JOIN result r ON rid.results_id = r.id
WHERE rid.is_active = 1 AND r.is_active = 1
GROUP BY cirl.level, cirl.name ORDER BY cirl.level;
```

### Innovations at readiness level >= 7 (advanced)
```sql
SELECT COUNT(*) as count
FROM results_innovations_dev rid
JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
JOIN result r ON rid.results_id = r.id
WHERE rid.is_active = 1 AND r.is_active = 1 AND cirl.level >= 7;
```

### Results in a specific region (e.g. Eastern Africa)
```sql
SELECT r.id, r.title, rt.name as result_type
FROM result r
JOIN result_region rr ON r.id = rr.result_id
JOIN clarisa_regions cr ON rr.region_id = cr.um49Code
JOIN result_type rt ON r.result_type_id = rt.id
WHERE rr.is_active = 1 AND r.is_active = 1
AND cr.name = 'Eastern Africa'
LIMIT 20;
```

### Results by CGIAR center
```sql
SELECT ci.acronym as center, COUNT(DISTINCT rc2.result_id) as result_count
FROM results_center rc2
JOIN clarisa_center cc ON rc2.center_id = cc.code
JOIN clarisa_institutions ci ON cc.institutionId = ci.id
JOIN result r ON rc2.result_id = r.id
WHERE rc2.is_active = 1 AND r.is_active = 1
GROUP BY ci.acronym ORDER BY result_count DESC;
```

### Partner institutions for a result type
```sql
SELECT ci.name as partner, ci.acronym, COUNT(DISTINCT rbi2.result_id) as result_count
FROM results_by_institution rbi2
JOIN clarisa_institutions ci ON rbi2.institutions_id = ci.id
JOIN result r ON rbi2.result_id = r.id
WHERE rbi2.is_active = 1 AND r.is_active = 1
AND rbi2.institution_roles_id = 2
AND r.result_type_id = 7
GROUP BY ci.name, ci.acronym ORDER BY result_count DESC LIMIT 20;
```

---

## Known Gotchas

1. **Table name typos:** `results_by_inititiative` (extra 'i'), `inititiative_id` column, `non_pooled_projetct_budget` (missing 'c'), `has_unkown_using` (typo for 'unknown')
2. **Duplicate SDG rows:** `clarisa_sdgs` has duplicated entries; use `WHERE usnd_code <= 17` or `DISTINCT`
3. **NULL years:** ~610 results have NULL `reported_year_id`
4. **is_active filtering:** Always include `WHERE is_active = 1` on both the result table AND junction tables
5. **Knowledge products lack titles:** Many KP results have NULL title/description -- the actual metadata is in `results_knowledge_product` and `results_kp_metadata`
6. **Country name format:** Some names are formal (e.g. "Tanzania, United Republic", "The Socialist Republic of Viet Nam") -- use LIKE for flexible matching
7. **Innovation readiness level IDs:** IDs are 11-20 (not 0-9). The `level` column in `clarisa_innovation_readiness_level` has the 0-9 value
8. **results_innovations_dev.results_id:** Note the column is `results_id` (with 's'), not `result_id`
9. **results_innovations_use.results_id:** Same pattern -- `results_id` (with 's')
10. **results_knowledge_product.results_id:** Same pattern
11. **clarisa_center.institutionId:** CamelCase column, links to `clarisa_institutions.id`
12. **Region hierarchy:** `clarisa_regions.parent_regions_code` is self-referential for sub-regions (e.g. Eastern Africa -> Sub-Saharan Africa -> Africa)
