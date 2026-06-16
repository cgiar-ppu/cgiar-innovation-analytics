# Incident Post-Mortem — "2024" query returned an all-years / 2025-flavored snapshot

**Date:** 2026-06-15
**Reported by:** Jose (user), via DEV chat at https://innovation-analytics-dev.synapsis-analytics.com/chat
**Session:** 231c8e13 ("Query the PRMS database to show me all results reported under the Resilient Agrifood Systems initiative in 2024")
**Severity:** High — produced numbers that do not match the official PowerBI dashboard and a programme breakdown that is structurally impossible for the requested year.

---

## 1. What the user asked

1. *"Query the PRMS database to show me all results reported under the Resilient Agrifood Systems initiative **in 2024**."*
2. Follow-up: *"We have 5 million USD scaling fund and we want to invest in a diverse set of scaling-ready innovations in Africa."* (no year restated — **2024 context carried over**)

## 2. What the agent produced (WRONG)

- **176** scaling-ready innovations (IRL 7+) in Africa: IRL7=63, IRL8=42, IRL9=71.
- Top programme: **"SP01 Breeding for Tomorrow" = 33**, mixed with INIT-01, INIT-13, SP03, SP09, etc.

## 3. What was actually correct for 2024

Verified against `prdb_fresh.sqlite` (June 13 snapshot), alive-in-year 2024, Africa, IRL 7+:

| Metric | Agent (wrong) | Correct 2024 | Error |
|---|---|---|---|
| Total IRL 7+ | 176 | **111** | +59% |
| IRL 7 | 63 | 40 | |
| IRL 8 | 42 | 25 | |
| IRL 9 | 71 | 46 | |
| Top programme | SP01 Breeding for Tomorrow (33) | **INIT-01 Accelerated Breeding (46)** | wrong era |

**SP01 "Breeding for Tomorrow" has 105 records — ALL in 2025, ZERO in 2024.** Its presence in a "2024" answer is proof the query was not year-scoped.

## 4. Root cause

The agent built the **all-years latest-phase dedup CTE** (the `canon` CTE / "QAed snapshot selector") and **never added a `reported_year_id = 2024` filter**. Three compounding faults, each of which the existing guidance already warns against:

1. **Missing year filter.** The user said 2024; the SQL contained no `reported_year_id`. The dominant fault.
2. **Wrong dedup model for a per-year question.** Even with a year intended, a year-scoped list/breakdown must use **alive-in-year** scope (`source='Result' AND is_active=1 AND status_id=2 AND reported_year_id=:year`), not the all-years latest-phase CTE. The system prompt calls this "the SINGLE most important rule."
3. **Era mixing.** The `canon` CTE keeps each result_code's **latest** reporting phase. Version 6 (Reporting 2025) = `portfolio_id=3`. So any code that continued into 2025 was returned with its **2025 Science-Program attributes (SP01–SP13)**, blended with codes whose latest phase was still an Initiative (INIT-##). A single-year answer can only belong to one portfolio era.

### Why the guidance failed to prevent it

The correct rules were **already injected in full** — but:
- The most **prominent, repeatedly copy-pasteable SQL block** in the entire system prompt is the all-years `canon` dedup CTE (it appears ~4×, labelled "CANONICAL", "copy-paste verbatim"). The shorter alive-in-year pattern is mostly described in prose. The agent pattern-matched to the most salient reusable block and bolted Africa+IRL filters onto it.
- The cookbook had **count** recipes (how many in year X) but **no recipe for a year-scoped list/subset/breakdown** ("all results under initiative X in 2024", "scaling-ready innovations in Africa in 2024") — which is exactly the shape of this request.
- **No tripwire** existed for the observable contradiction (SP-codes in a 2024 answer), and **no carry-forward rule** told the agent to keep the year from turn 1 when answering turn 2.

## 5. Fix applied (guidance)

1. **`synapsis/system_prompt.py`** — added a loud `⛔ STOP — YEAR-SCOPE PRE-FLIGHT` gate placed **before** the canonical CTE blocks, with: the mandatory `reported_year_id` rule, the alive-in-year-for-subsets rule, the SP-vs-INIT era tripwire, and a carry-forward rule.
2. **`references/prms_query_cookbook.md`** — added a top-of-file Year-Scope Protocol, a new **Recipe 8: Year-scoped subset / list / breakdown** (with the verified 2024 Africa IRL7+ example = 111), and an **era-mixing anti-pattern** quoting the exact failing query from this incident.

## 6. Recommended follow-up (code, defense-in-depth — not yet applied)

Add a lightweight guard in the `prms_query` tool: if the `question` text (or recent turn) names a year but the `sql` contains no `reported_year_id`, return a soft warning in the tool result. Belt-and-suspenders beyond the prompt. Requires deploy via CI/CD.
