# CGIAR Terminology Glossary

Comprehensive glossary of terms used across CGIAR systems, the innovation analytics platform, and the scaling readiness framework. Organized by domain.

---

## CGIAR System and Organizational Terms

| Term | Definition | Context |
|------|-----------|---------|
| **CGIAR** | Global partnership of 15 agricultural research centers focused on food security, poverty reduction, and environmental sustainability. Formerly "Consultative Group on International Agricultural Research." | Top-level organizational entity |
| **OneCGIAR** | The 2022+ reform integrating formerly independent centers into a unified research portfolio with shared governance, strategy, and results reporting. | Organizational reform context |
| **Science Programme** | Thematic research programmes (SP01-SP08) that form the core of the 2025-2030 portfolio. Each covers a major domain: breeding, farming, livestock, landscapes, nutrition, climate, policy, or food security. | Primary organizational unit for research (replaces CRPs) |
| **Accelerator** | Cross-cutting programmes (SP09-SP12) that amplify Science Programme impact: Scaling for Impact, Gender Equality, Capacity Sharing, Digital Transformation. | Organizational unit enabling cross-programme impact |
| **Initiative** | A time-bound, results-oriented research project (INIT-01 to INIT-35) under the 2022-2024 portfolio. Each maps to one or more Science Programmes. The primary unit for PRMS reporting. | 35 active initiatives; being transitioned to the SP structure |
| **CRP** | CGIAR Research Program. The pre-2022 organizational structure, now replaced by Initiatives and Science Programmes. Legacy CRPs still appear in historical data. | Historical; replaced by Initiatives |
| **Action Area** | Three strategic groupings: (1) Systems Transformation, (2) Resilient Agrifood Systems, (3) Genetic Innovation. Initiatives and SPs align to Action Areas. | Strategic framework level above Science Programmes |
| **Impact Area** | Five high-level goals: Nutrition/Food Security, Poverty Reduction, Gender Equality, Climate Adaptation, Environmental Health. All CGIAR work maps to at least one. | Highest-level outcome categories |
| **PPU** | Portfolio Performance Unit. The CGIAR unit responsible for monitoring portfolio performance, managing PRMS, and providing analytics to leadership. | Organizational unit; key stakeholder for this platform |
| **Center** | One of 15 independent CGIAR research centers (e.g., IRRI, CIMMYT, ICRISAT). Each has a specific commodity or thematic mandate and serves as the implementing entity for research. | Organizational entity; "lead center" in PRMS results |
| **SO** | CGIAR System Organization. The central coordinating body for the CGIAR partnership. | Organizational entity (CENTER-16 in PRMS) |
| **NARS** | National Agricultural Research Systems. Country-level public research organizations that are key delivery and scaling partners. | External partner category |

## Data Systems and Platforms

| Term | Definition | Context |
|------|-----------|---------|
| **PRMS** | Performance and Results Management System. CGIAR's central database for tracking all research outputs, outcomes, and impacts. Contains ~32,000 results across 197 tables. The primary data source for this platform. | Core data system; queried via SQLite |
| **CLARISA** | CGIAR's reference data API providing controlled vocabularies for countries, regions, institutions, innovation readiness levels, SDG targets, and other master data. PRMS relies on CLARISA for data standardization. | Reference data system; master data source |
| **OIKER** | Open Innovation Key Evidence Repository. A platform for sharing innovation evidence and documentation. | Evidence management system |
| **ATR** | Annual Technical Report. The yearly reporting process where all Initiatives submit their results to PRMS. The ATR cycle drives the bulk of data entry. | Reporting process; annual cycle |
| **TOC** | Theory of Change. The causal framework linking activities to outputs to outcomes to impacts. Each Initiative has a TOC, and PRMS results are mapped to specific TOC elements. In data: `toc_mapping` links results to programme-level TOC results. | Strategic planning and results mapping framework |
| **KRS** | Key Result Story. A narrative document highlighting significant results, often linked to PRMS results as evidence. | Evidence/reporting format |
| **CG Insights** | Planned centralized front-end for CGIAR's AI-powered analytical products. Will serve as a unified portal for multiple tools including this platform. | Future ecosystem; integration target |
| **CE 360** | CGIAR Engagement 360. A related platform for stakeholder engagement analytics. | Adjacent platform |

## Innovation and Scaling Terms

| Term | Definition | Context |
|------|-----------|---------|
| **Innovation** | In CGIAR: a knowledge, technology, or practice (new or adapted) developed, tested, and validated to achieve specific development impact. Tracked as `innovation_development` results in PRMS. | Core entity; result_type_id = 7 in PRMS |
| **Innovation Package** | A bundle of complementary innovations designed for scaling. Includes a core innovation plus supporting innovations that address barriers. | result_type_id = 10; 255 packages in PRMS |
| **Complementary Innovation** | An innovation within an Innovation Package that supports the core innovation by addressing enabling environment barriers. | result_type_id = 11; 612 in PRMS |
| **IRL** | Innovation Readiness Level. A 0-9 scale measuring how ready an innovation is for scaling, from Idea (0) to Proven Innovation (9). Broader than TRL -- includes social, institutional, and market readiness. | Key metric; stored in `results_innovations_dev` |
| **TRL** | Technology Readiness Level. The technical maturity component of innovation readiness (0-9). IRL is the broader CGIAR equivalent. | Technical readiness subset of IRL |
| **IPSR** | Innovation Packages and Scaling Readiness. The formal CGIAR process for assessing scaling potential of innovation bundles. Conducted through structured workshops. | Assessment methodology |
| **Scaling Readiness** | The systematic framework for assessing, optimizing, and translating innovation potential into real-world impact at scale. Three phases: Identify, Assess & Optimize, Translate. | Core framework; SP09 leads this |
| **Scaling Delivery Strategy** | The primary output document of the scaling process. 14 sections + Executive Summary describing how an innovation will be scaled from research to widespread adoption. | Key deliverable of scaling work |
| **Scaling Pathway** | The route to scale: public-sector led, market-led, or public-private partnership. Can change across scaling phases. | Strategic choice in scaling |
| **Responsible Scaling** | CGIAR's ethical framework for scaling: gender equity, environmental sustainability, do-no-harm, co-design with local stakeholders. | Cross-cutting principle |
| **S4I** | Scaling for Impact. CGIAR's strategic framework and accelerator (SP09) for moving innovations from research to scale. | Programme and framework |
| **Enabling Environment** | The external conditions (policy, regulation, institutions, infrastructure) that enable or constrain innovation scaling. | Analytical concept in scaling |

## PRMS Result Types

| Term | Result Type ID | Definition | Count in DB |
|------|---------------|-----------|-------------|
| **Innovation Development** | 7 | New technologies, practices, policies being developed and validated | 5,236 |
| **Knowledge Product** | 6 | Publications, datasets, reports, and other knowledge outputs | 13,800 |
| **Capacity Sharing for Development** | 5 | Training events, workshops, educational programmes, capacity development | 4,844 |
| **Innovation Use** | 2 | Documented adoption and uptake of innovations by users beyond the project | 1,228 |
| **Policy Change** | 1 | Influence on or enactment of policies, strategies, legal instruments | 682 |
| **Innovation Package** | 10 | Bundles of complementary innovations designed for scaling | 255 |
| **Complementary Innovation** | 11 | Supporting innovations within an Innovation Package | 612 |
| **Other Output** | 8 | Outputs not fitting other categories | 4,693 |
| **Other Outcome** | 4 | Outcomes not fitting other categories | 596 |
| **Capacity Change** | 3 | Changes in capacity (knowledge, attitudes, skills, relationships) | 47 |
| **Impact Contribution** | 9 | Documented contributions to high-level impact | 12 |

## Result Levels

| Level | Name | Definition |
|-------|------|-----------|
| Impact | Impact | A durable change in the condition of people and their environment |
| Action Area Outcome | Action Area outcome | A change in knowledge, attitudes, skills, and/or relationships (KASR) |
| Outcome | Outcome | A change in KASR manifesting as behavior change within spheres of influence |
| Output | Output | Knowledge, technical, or institutional advancement produced by CGIAR activities |

## Funding and Financial Terms

| Term | Definition | Context |
|------|-----------|---------|
| **W1** | Window 1 funding. Pooled, unrestricted funding allocated by the CGIAR System Council. | Funding mechanism |
| **W2** | Window 2 funding. Pooled funding allocated to specific Initiatives or CRPs. | Funding mechanism |
| **W3** | Window 3 funding. Project-specific grants from donors with restricted scope and reporting. | Funding mechanism; tracked in PRMS projects |
| **Bilateral** | Direct funding agreements between individual donors and CGIAR centers, outside the pooled windows. | Most common funding mechanism in PRMS (197 projects) |
| **Bilateral - Restricted** | Bilateral funding with additional restrictions on use and reporting scope. | Funding sub-type |

## Geographic and Demographic Terms

| Term | Definition | Context |
|------|-----------|---------|
| **Geographic Scope** | How broadly a result applies: Global (1), Regional (2), Multi-national (3), National (4), Sub-national (5). | PRMS field `geographic_scope_id` |
| **CGIAR Regions** | CGIAR's own regional groupings (8 regions), mapped from UN M49 regions. Differ from UN regions. | Used for portfolio-level geographic analysis |
| **GESI** | Gender Equality and Social Inclusion. Cross-cutting concern integrated into all CGIAR strategies and reporting. | Cross-cutting theme |
| **Cross-cutting Tags** | Gender, climate change, nutrition, environmental/biodiversity, and poverty tags applied to each result on a 3-level scale. | PRMS metadata for each result |

## Analytical and Platform Terms

| Term | Definition | Context |
|------|-----------|---------|
| **Megatrend** | A major long-term force shaping food, land, and water systems. CGIAR's foresight research tracks megatrends including climate change, urbanization, diet transition, demographic shifts, etc. | Used in portfolio planning and scenario analysis |
| **Demand Signaling** | Identifying market and policy demand for specific innovations or research outputs. Used in portfolio planning. | Analytical concept |
| **Portfolio Health** | Assessment of a programme's innovation pipeline: distribution across readiness levels, geographic coverage, thematic balance, partner diversity. | Analytical framework |
| **PRMS-validated** | Data that comes directly from the PRMS database and is verified through the official reporting process. Distinguished from AI-inferred insights. | Data provenance label in this platform |
| **AI-inferred** | Insights generated by the platform's analytical engine that go beyond what is explicitly stated in the PRMS data. Includes pattern analysis, projections, and recommendations. | Data provenance label in this platform |
| **Source Attribution** | The practice of clearly indicating whether each claim or data point comes from PRMS data, literature, or AI analysis. A core design principle of the platform. | Platform design principle |

## Policy Terms

| Term | Definition | Context |
|------|-----------|---------|
| **Policy Type** | Classification of policy results: (1) Program, budget or investment, (2) Legal instrument, (3) Policy or strategy. | PRMS field for policy_change results |
| **Policy Stage** | Progress of policy influence: Stage 1 (research taken up), Stage 2 (policy enacted), Stage 3 (evidence of impact). | PRMS field for policy_change results |

## Screening and Assessment Terms

| Term | Definition | Context |
|------|-----------|---------|
| **Screening** | Initial evaluation of innovation evidence against 11 eligibility criteria (3 mandatory, 8 threshold) to determine scaling eligibility. | First step in scaling pipeline |
| **Eligibility Categories** | Eligible (5+ threshold met), Conditionally Eligible (exactly 4 met), Not Yet Eligible (0-3 met or mandatory failed). | Screening outcome |
| **Scorecard** | Evidence quality evaluation of each of the 14 strategy sections, scored 0-10 per section. | Strategy quality assessment |
| **Evidence Quality Tier** | Document-level quality: high, medium, low, or unknown. Derived from automated quality checks. | Document classification |

## Acronyms Quick Reference

| Acronym | Full Form |
|---------|-----------|
| ATR | Annual Technical Report |
| CLARISA | CGIAR reference data API (controlled vocabularies) |
| CRP | CGIAR Research Program (legacy) |
| GESI | Gender Equality and Social Inclusion |
| IPSR | Innovation Packages and Scaling Readiness |
| IRL | Innovation Readiness Level |
| KRS | Key Result Story |
| NARS | National Agricultural Research Systems |
| OIKER | Open Innovation Key Evidence Repository |
| PPU | Portfolio Performance Unit |
| PRMS | Performance and Results Management System |
| S4I | Scaling for Impact |
| SDG | Sustainable Development Goal |
| SO | System Organization |
| SP | Science Programme |
| TOC | Theory of Change |
| TRL | Technology Readiness Level |
