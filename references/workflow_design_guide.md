# Workflow Design Guide

## Overview
Workflows in Synapsis chain multiple specialist agents into sequential pipelines.
Each agent receives the output of the previous agent as its input.

## Available Agents

| Agent | Best For |
|-------|----------|
| data_analysis | EDA, hypothesis testing, regression, data wrangling |
| visualization_reporting | Charts, dashboards, reports, figure exports |
| research_methodology | Study design, sampling, power analysis |
| code_automation | Pipelines, ETL, scraping, API integration, scripting |
| computer_use | GUI interaction, browsing, document editing |

## Common Pipeline Patterns

### 1. Data → Visualization
**Agents**: data_analysis → visualization_reporting
**Use When**: You have raw data and want analyzed charts/reports
**Example Prompt**: "Analyze the sales dataset in uploads/ and create a comprehensive dashboard with key metrics"

### 2. Research → Analysis → Report
**Agents**: research_methodology → data_analysis → visualization_reporting
**Use When**: Starting from a research question with data available
**Example Prompt**: "Design an A/B test for our new feature, analyze the results in experiment_data.csv, and generate a report"

### 3. Scrape → Analyze
**Agents**: code_automation → data_analysis
**Use When**: Need to collect data before analyzing
**Example Prompt**: "Scrape pricing data from [source] and perform competitive analysis"

### 4. Full Pipeline
**Agents**: code_automation → data_analysis → visualization_reporting
**Use When**: End-to-end data pipeline from collection to visualization
**Example Prompt**: "Download the dataset, clean and analyze it, then create publication-quality figures"

## Design Tips
1. **Keep pipelines focused**: 2-3 agents is optimal. More agents increase latency and cost.
2. **Be specific in prompts**: The initial prompt sets context for all agents.
3. **Check intermediate outputs**: Each agent's output is passed to the next. Ambiguous outputs cause cascade issues.
4. **Use the right agent order**: Data preparation before analysis, analysis before visualization.
5. **Save intermediate results**: Agents can write to /workspace/ for later reference.

## Limitations
- Pipelines are sequential (no branching or parallel execution yet)
- Each agent starts fresh (no shared memory within a pipeline run)
- Long pipelines may timeout (max_turns applies per agent)
