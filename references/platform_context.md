# Platform Context: CGIAR Innovation Analytics Platform

## What This Platform Is

The CGIAR Innovation Analytics Platform is a modular AI-powered analytical tool for CGIAR innovation portfolio management. It enables programme leaders, accelerator leads, and portfolio managers to interrogate CGIAR's innovation data through natural language conversation, generate visualizations, run scenario analyses, and identify scaling partners.

This is "Project 2" in the CG Insights ecosystem -- built specifically for the Portfolio Performance Unit (PPU) and CGIAR programme leadership to support data-driven decision-making about the innovation portfolio.

## The Four Modules

### Module 1: Conversational Data Interrogation
Users ask natural language questions about CGIAR innovations and receive sourced answers drawn from the PRMS database. Every answer includes clear attribution: which PRMS tables and records the data came from, and whether claims are PRMS-validated or AI-inferred.

**Example queries:**
- "How many innovations are tagged for East Africa?"
- "Which science programmes have the fewest innovations at readiness level 7+?"
- "What is the geographic distribution of innovations from INIT-01?"
- "Show me all policy changes from the Sustainable Farming programme"

### Module 2: Self-Serve Visualization Builder
Users request charts through conversation and receive interactive visualizations. Supports bar, line, area, pie/donut, scatter, map (choropleth), and heatmap chart types. Charts can be pinned to a dashboard view for ongoing monitoring.

**Example queries:**
- "Show me a bar chart of innovations by science programme"
- "Create a map showing innovation density by country in Sub-Saharan Africa"
- "Plot the readiness level distribution for the Breeding for Tomorrow programme over time"

### Module 3: Scenario Planning
Forward-looking "what if" analysis that combines PRMS portfolio data with scaling readiness framework logic. Generates comparative before/after visualizations.

**Example queries:**
- "What would our East Africa portfolio look like if we focused on innovations at readiness levels 5-7?"
- "If we increase biofortification funding by 30%, which innovations could reach readiness level 9?"
- "Model the impact of adding 3 new partner organizations to our South Asia scaling pipeline"

### Module 4: Partner Identification
Combines PRMS partner data with web search to identify existing and potential partners for scaling specific innovations. Clearly distinguishes between PRMS-sourced partners and AI-suggested partners.

**Example queries:**
- "Which partners are most active in biofortification innovations?"
- "Find potential partners for scaling drone-based crop monitoring in South Asia"
- "Who are the key delivery partners for innovations at readiness level 8+ in West Africa?"

## Target Users

| User | Role | Primary Needs |
|------|------|--------------|
| Marc Schut | Scaling Readiness lead (SP09) | Portfolio health monitoring, scaling pipeline visibility, partner networks |
| Nikki Tierney | PPU coordination | Portfolio-level analytics, reporting support, data quality oversight |
| Programme Leaders | Lead SP01-SP08 | Innovation pipeline for their programme, geographic coverage, readiness distribution |
| Accelerator Leads | Lead SP09-SP12 | Cross-programme analytics, scaling readiness trends, capacity needs |
| Portfolio Managers | PPU analysts | Aggregate metrics, trend analysis, funder reporting |
| External Funders | BMGF, USAID, FCDO, etc. | Impact evidence, geographic reach, return on investment |

## Key Use Cases

### 1. Portfolio Planning in New Geographies
A programme leader exploring expansion to a new region can ask: "What innovations do we have available for scaling in West Africa?" and receive a filtered view showing innovations by readiness level, type, and current partners in that region, along with gap analysis.

### 2. Budgeting Support for Programme Leaders
When preparing budget proposals, leaders can ask: "What is the current readiness distribution in my programme and what investment would be needed to move innovations from level 5-6 to level 7+?" and receive a quantified analysis.

### 3. Partner Identification for Scaling
When seeking partners for a specific innovation, users can ask: "Which organizations have experience scaling agricultural technologies in Bangladesh?" and receive both PRMS-documented partners and AI-suggested potential partners from web research.

### 4. Portfolio Health Assessment
PPU managers can ask: "Which programmes have unhealthy innovation pipelines?" and receive analysis showing programmes with too few innovations at scaling-ready levels, geographic concentration risks, or partner dependency issues.

### 5. Cross-Programme Synergy Identification
Users can explore: "Are there innovations across different programmes that address similar challenges in climate adaptation?" to identify potential Innovation Package opportunities.

## Data Sources

### Primary: PRMS Database
- **Format:** SQLite database (197 tables, ~398MB)
- **Content:** 32,005 results including 5,236 innovation developments, 13,800 knowledge products, 4,844 capacity sharing events, 1,228 innovation use records, 682 policy changes
- **Coverage:** All CGIAR Initiatives and Science Programmes, 2022-2024 reporting cycles
- **Refresh:** Snapshot from March 2026; periodic refresh planned
- **Schema reference:** See PRMS schema analysis documentation

### Supplementary: Innovation Excel Export
- 828 rows covering innovation developments, capacity sharing, and policy changes
- Contains additional fields not in the main results query (TOC results, action area outcomes, evidence links)

### Planned Future Sources
- **Impact Compendium** -- Published CGIAR impact evidence (when received from Marc)
- **Marc's research papers** -- Scaling readiness methodology papers
- **Maui's foresight research** -- Megatrend analysis and scenario data
- **CLARISA API** -- Live reference data for validation (currently using local snapshot)

## Design Principles

### 1. Source Attribution (PRMS-validated vs AI-inferred)
Every data point and claim made by the platform is labeled with its provenance:
- **PRMS-validated:** Data drawn directly from the PRMS database, with specific table/record references
- **AI-inferred:** Insights generated through analysis, pattern recognition, or reasoning beyond what is explicitly stated in the data

This distinction is critical for maintaining trust with CGIAR stakeholders who need to know exactly what comes from the official system of record versus what is analytical interpretation.

### 2. Modular Architecture
Each module is independently deployable, testable, and demonstrable. If one module stalls, others are not blocked. This aligns with the agile sprint methodology agreed with the PPU.

### 3. Forward-Looking Decision Support over Retrospective Filtering
The platform is not just a dashboard for viewing historical data. Its primary value is in supporting forward-looking decisions: where to invest, which innovations to prioritize for scaling, which partnerships to pursue, and what scenarios to plan for.

### 4. Conversational Interface as Primary Interaction
Rather than presenting fixed dashboards, the platform uses natural language conversation as the primary interface. This lowers the barrier to entry for non-technical users and enables exploratory analysis that would be impossible with pre-built visualizations.

### 5. Responsible AI Use
The platform acknowledges the limitations of AI-generated analysis, avoids presenting inferences as facts, and always provides the user with the underlying data to verify claims. The agent should be transparent about confidence levels and data gaps.

## Technical Architecture

- **Backend:** FastAPI + Claude Agent SDK (Python)
- **Frontend:** React 19 + shadcn/ui + Tailwind CSS (TypeScript)
- **AI Model:** Claude Opus 4.6 (orchestrator) with specialist subagents
- **Data Access:** SQLite queries via agent tool (`prms_query`)
- **Visualization:** Recharts-based interactive charts
- **Deployment:** macOS native (development), AWS (production)
- **Port:** 7780

## Specialist Subagents

| Agent | Role | Primary Tools |
|-------|------|--------------|
| PRMS Data Analyst | Queries PRMS, generates statistics, answers data questions | prms_query, data analysis |
| Scaling Strategy Assessor | Understands readiness levels, scaling pathways, portfolio health | Scaling framework reference, prms_query |
| Visualization Specialist | Generates charts from PRMS data | create_chart, prms_query |
| Research Analyst | Handles literature, external sources, partner identification | Web search, prms_query |

## Relationship to Other CGIAR Tools

| Tool | Relationship |
|------|-------------|
| CG Insights | Parent ecosystem; this platform will integrate as one product within CG Insights |
| Scaling Strategies 2.0 (sc-cgiar-agent) | Sister product; focuses on generating Scaling Delivery Strategies from evidence documents |
| Innovation Portfolio Management Tool (IPM) | Predecessor prototype; Streamlit-based portfolio wizard that this platform supersedes |
| CGIAR Demand-Supply Explorer | Related product; demand intelligence for CGIAR research prioritization |
| Bilateral Results Uploader | Data ingestion tool; uploads bilateral project results to PRMS |
