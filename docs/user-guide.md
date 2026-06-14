# CGIAR Innovation Analytics Platform — User Guide

*A practical guide for getting insights from CGIAR's innovation portfolio*

---

## 1. What is the Innovation Analytics Platform?

The Innovation Analytics Platform is an AI-powered assistant built specifically for CGIAR. Think of it as a knowledgeable colleague who has read every record in CGIAR's Performance and Results Management System (PRMS) and can instantly answer questions about the organization's innovation portfolio — in plain language, with charts, and with strategic context.

Behind the scenes, the platform is powered by Claude, Anthropic's advanced AI reasoning engine. It connects directly to CGIAR's PRMS database, which contains over 27,800 results, 4,600+ innovations, data from 183 countries, and outputs from all 55 active initiatives. Instead of navigating spreadsheets or waiting for someone to pull a report, you can simply ask a question and get an answer — often with a chart to go along with it.

The platform goes beyond basic data retrieval. It can model "what if" scenarios to support strategic planning (e.g., "What would happen if we shifted investment toward a particular initiative?"), identify potential partners for scaling innovations, and synthesize cross-cutting insights that would take a human analyst days to compile. Every response clearly labels whether data comes directly from PRMS or is a modeled projection, so you always know what you're looking at.

---

## 2. Getting Started

### Accessing the platform

Open your web browser and go to:

> **https://innovation-analytics-dev.synapsis-analytics.com**

No installation is needed — the platform runs entirely in your browser.

### What you will see

The interface is a **chat window**, similar to ChatGPT or other AI assistants, but purpose-built for CGIAR data. You type a question or request in the message box at the bottom, press Enter, and the platform responds with text, tables, or interactive charts.

At the top of the interface, you will find a **dashboard** showing key portfolio indicators at a glance:

| Metric | Current Value |
|--------|---------------|
| Total Results | 27,803 |
| Total Innovations | 4,664 |
| Innovation Uses | 559 |
| Active Initiatives | 55 |
| Countries Covered | 183 |
| Knowledge Products | 12,850 |

The dashboard also includes pre-built charts: results by type, top countries, innovation readiness level distribution, and top initiatives by output.

### Starting a conversation

Simply type your question in natural language — no special syntax or query language needed. The platform understands context, so you can ask follow-up questions just as you would in a normal conversation.

---

## 3. What You Can Ask

The platform supports a wide range of questions. Here are examples organized by what you are trying to do.

### Data Queries — querying the PRMS database

These questions pull real, validated data directly from the PRMS system.

- **"How many innovations has CGIAR produced in the last 3 years?"**
- **"Which countries have the most policy change results?"**
- **"Show me all innovations at readiness level 7 or above"**
- **"What are the top 5 initiatives by number of knowledge products?"**
- **"How many innovation uses have been reported in Sub-Saharan Africa?"**

### Charts and Visualizations

Ask for a chart whenever you want a visual summary. The platform generates interactive charts directly in the chat.

- **"Create a bar chart comparing innovation outputs across the top 10 initiatives"**
- **"Show me a pie chart of result types across all of CGIAR"**
- **"Plot the distribution of innovation readiness levels"**
- **"Chart the number of results per year for the last 5 years"**

### Scenario Analysis — "what if" modeling

Use these questions when you are exploring strategic options. The platform will model hypothetical changes against real PRMS baseline data.

- **"What would happen if we doubled investment in the SAPLING initiative?"**
- **"Model shifting 20% of capacity from knowledge products to innovation development"**
- **"What if innovations at IRL 5-6 were fast-tracked to IRL 7?"**
- **"How would a portfolio-wide focus on climate adaptation change our output mix?"**

### Partner Identification

Find existing and potential partners for specific topics, geographies, or innovation areas.

- **"Who are the key partners working on climate adaptation in East Africa?"**
- **"Find potential partners for scaling drought-resistant crop innovations in South Asia"**
- **"Which private sector organizations are partnering with CGIAR on digital agriculture?"**
- **"List government partners involved in policy change results in Southeast Asia"**

### Strategic Insights

Ask big-picture questions that require synthesis across the portfolio.

- **"Summarize CGIAR's innovation portfolio strengths and gaps"**
- **"Which initiatives have the highest innovation-to-use conversion rate?"**
- **"What are the common characteristics of innovations that reach IRL 7 or above?"**
- **"Compare the output profiles of the top 5 initiatives"**

---

## 4. Tips for Getting Good Results

A few practical suggestions to get the most out of the platform:

- **Be specific.** The more detail you provide — country, initiative name, result type, time period — the more precise the answer. "How many innovations in Kenya in 2024?" will give you a sharper answer than "Tell me about innovations."

- **Ask for charts when you want a visual.** If a table of numbers would be easier to understand as a bar chart or pie chart, just say so. You can ask for a chart alongside your question: "Show me innovations by country and chart the top 10."

- **Use scenario analysis for strategic planning.** When you are preparing for a planning meeting or exploring options, the "what if" feature is designed for exactly that. Frame your question as a hypothetical: "What would happen if..."

- **Pay attention to data labels.** The platform clearly marks its responses:
  - **[PRMS-VALIDATED]** means the data comes directly from the PRMS database — these are confirmed facts.
  - **[SCENARIO-MODELED]** means the numbers are projections based on a hypothetical scenario — useful for planning, but not actual data.
  - **[WEB-SOURCED]** (in partner searches) means a suggestion found via web research, not a documented PRMS partnership.

- **Ask follow-up questions.** The platform remembers what you discussed earlier in the same session. If you asked about innovations in Kenya and want to drill deeper, you can say "Now break those down by readiness level" without repeating the context.

- **Ask for plain language.** If a response is too technical or dense, simply say "Can you explain that in simpler terms?" or "Summarize the key takeaway." The platform will adjust.

- **Export when needed.** If you want to share a conversation or analysis with colleagues, you can export it as a document (Markdown, HTML, Word, or PDF).

---

## 5. Understanding the Data

Here is a quick reference for the key concepts behind the data in the platform.

### Results (27,803 active)

A "result" is the core unit tracked in PRMS. It represents something CGIAR has produced or contributed to. Results come in several types:

- **Knowledge Products** (12,850) — Publications, datasets, tools, and other research outputs
- **Innovation Development** — The process of creating new technologies, practices, or approaches
- **Innovation Use** (559) — Evidence that an innovation has been adopted or used by its target audience
- **Policy Change** — Documented cases where CGIAR research influenced policy
- **Capacity Sharing** — Activities that build capacity in partner organizations or countries
- **Other Impact** — Additional outcome and impact categories

### Innovations (4,664)

Innovations are a specific category of result — new or significantly improved technologies, practices, or approaches. Each innovation is tracked through its lifecycle using Innovation Readiness Levels.

### Innovation Readiness Levels (IRL 0-9)

This scale measures how mature an innovation is:

| Level | Stage | What it means |
|-------|-------|---------------|
| 0-1 | Idea / Concept | The innovation is a hypothesis or early concept |
| 2-3 | Proof of Concept | Initial evidence that it works in controlled settings |
| 4-5 | Piloting | Tested in real-world conditions with target users |
| 6-7 | Validated | Proven effective; ready for or beginning wider adoption |
| 8-9 | Scaling / At Scale | Being adopted broadly by end users and partners |

Higher IRL means closer to real-world impact. When the platform mentions "IRL 7 or above," it means innovations that are validated and either ready to scale or already scaling.

### Initiatives (55 active)

Initiatives are CGIAR's organizational units — the programs and projects that produce results. Each initiative has a specific focus area (e.g., climate adaptation, livestock health, digital tools) and a portfolio of results.

### Partners (48,000+ partner links)

CGIAR works with a vast network of partners — research institutions, governments, NGOs, private sector companies, and CGIAR Centers. The platform can identify who is working on what, and where.

### Countries (183)

PRMS tracks where results are being produced and applied. You can filter or ask about any country or region.

---

## 6. Getting Help

**For questions about the platform or unexpected behavior:**
Contact the Synapsis Analytics team at **smith-code@synapsis-analytics.com**

**For questions about PRMS data accuracy or methodology:**
Reach out to the CGIAR Performance and Results team.

**For feedback and feature requests:**
We welcome suggestions. Send them to the Synapsis Analytics team and we will prioritize them for upcoming releases. The platform is actively being developed, and your input directly shapes what gets built next.

---

*Last updated: May 2026*
