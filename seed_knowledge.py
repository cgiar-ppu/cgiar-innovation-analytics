"""
Synapsis Analytics Agent — Seed Knowledge Script

Pre-loads foundational memories into the agent's MCP memory system.
These memories provide the agent with general analytics best practices,
statistical guidance, and methodology references.

Usage:
    python seed_knowledge.py [--base-url http://localhost:7777]
"""

import argparse
import json
import sys
import time

import requests

SEED_MEMORIES = [
    # ---- Statistical Test Selection ----
    {
        "category": "best_practice",
        "content": (
            "Statistical test selection guide:\n"
            "- Comparing 2 group means: t-test (independent or paired)\n"
            "- Comparing 3+ group means: one-way ANOVA → post-hoc (Tukey, Bonferroni)\n"
            "- Non-normal data or ordinal: Mann-Whitney U, Kruskal-Wallis\n"
            "- Categorical association: Chi-square test, Fisher's exact (small N)\n"
            "- Correlation: Pearson (linear, normal), Spearman (monotonic, ordinal)\n"
            "- Prediction: Linear regression (continuous), logistic (binary outcome)\n"
            "- Time-to-event: Kaplan-Meier, Cox proportional hazards\n"
            "Always check assumptions before selecting a test."
        ),
        "importance": 9,
        "tags": ["statistics", "hypothesis-testing", "test-selection"],
    },
    # ---- Effect Sizes ----
    {
        "category": "methodology_note",
        "content": (
            "Effect size interpretation (Cohen's conventions):\n"
            "- Cohen's d: small=0.2, medium=0.5, large=0.8\n"
            "- Pearson r: small=0.1, medium=0.3, large=0.5\n"
            "- Cohen's f: small=0.1, medium=0.25, large=0.4\n"
            "- Odds ratio: small=1.5, medium=2.5, large=4.3\n"
            "- Eta-squared: small=0.01, medium=0.06, large=0.14\n"
            "Always report effect sizes alongside p-values. Statistical significance "
            "does not imply practical significance."
        ),
        "importance": 9,
        "tags": ["effect-size", "statistics", "reporting"],
    },
    # ---- Sample Size Rules of Thumb ----
    {
        "category": "methodology_note",
        "content": (
            "Sample size rules of thumb:\n"
            "- Regression: 10-20 observations per predictor variable\n"
            "- Factor analysis: 5-10 subjects per variable, minimum 100\n"
            "- Chi-square: expected cell count >= 5\n"
            "- t-test: 30+ per group for CLT; use exact methods for smaller N\n"
            "- Survey: margin of error = 1.96 * sqrt(p*(1-p)/n) for 95% CI\n"
            "- A/B test: use power analysis with MDE, baseline rate, alpha, power\n"
            "- Cluster designs: inflate by DEFF = 1 + (m-1)*ICC\n"
            "Always run formal power analysis when possible."
        ),
        "importance": 8,
        "tags": ["sample-size", "power-analysis", "rules-of-thumb"],
    },
    # ---- Data Quality Checklist ----
    {
        "category": "best_practice",
        "content": (
            "Data quality checklist before analysis:\n"
            "1. Check dimensions (rows, columns) and data types\n"
            "2. Assess missing data: pattern (MCAR/MAR/MNAR), percentage per variable\n"
            "3. Look for duplicates (exact and near-duplicates)\n"
            "4. Check ranges and distributions for each variable\n"
            "5. Identify outliers (IQR method, z-scores, domain knowledge)\n"
            "6. Verify categorical levels (typos, inconsistent coding)\n"
            "7. Check date formats and time zones\n"
            "8. Assess data lineage and collection methodology\n"
            "Document all cleaning decisions for reproducibility."
        ),
        "importance": 9,
        "tags": ["data-quality", "eda", "cleaning", "checklist"],
    },
    # ---- Visualization Best Practices ----
    {
        "category": "best_practice",
        "content": (
            "Visualization best practices:\n"
            "- Choose chart type by data: bar (categorical), line (time series), "
            "scatter (relationship), histogram (distribution), heatmap (correlation)\n"
            "- Use colorblind-friendly palettes (viridis, Set2, ColorBrewer)\n"
            "- Always label axes with units, add descriptive titles\n"
            "- Minimize chartjunk: remove gridlines, borders, unnecessary legends\n"
            "- Start y-axis at 0 for bar charts; use log scale when appropriate\n"
            "- Use small multiples instead of 3D charts\n"
            "- Export at 300 DPI for publications (PNG or SVG)\n"
            "- Use consistent styling across figures in a report"
        ),
        "importance": 8,
        "tags": ["visualization", "charts", "best-practices", "design"],
    },
    # ---- Scope Boundaries ----
    {
        "category": "best_practice",
        "content": (
            "Agent scope boundaries:\n"
            "IN SCOPE: Data analysis, visualization, research methodology, code/automation, "
            "report generation, statistical guidance, EDA, power analysis\n"
            "OUT OF SCOPE: Production system administration, medical diagnosis, "
            "legal advice, real-time trading decisions\n"
            "When asked about out-of-scope topics: Acknowledge the question, "
            "explain it's outside scope, suggest the appropriate professional resource."
        ),
        "importance": 10,
        "tags": ["scope", "boundaries"],
    },
    # ---- Analyst Workflow ----
    {
        "category": "best_practice",
        "content": (
            "Recommended analyst workflow:\n"
            "1. DEFINE: Clarify the question, success metrics, and deliverables\n"
            "2. EXPLORE: Profile the data (shape, types, distributions, missing values)\n"
            "3. CLEAN: Handle missing data, outliers, duplicates, type conversions\n"
            "4. ANALYZE: Apply appropriate methods, check assumptions\n"
            "5. VISUALIZE: Create clear, honest charts that tell the story\n"
            "6. COMMUNICATE: Write findings in plain language with caveats\n"
            "7. REPRODUCE: Save scripts, document decisions, version outputs"
        ),
        "importance": 10,
        "tags": ["workflow", "process", "methodology"],
    },
    # ---- Regression Diagnostics ----
    {
        "category": "methodology_note",
        "content": (
            "Regression diagnostics checklist:\n"
            "1. Linearity: residuals vs fitted plot (should show no pattern)\n"
            "2. Normality: Q-Q plot of residuals, Shapiro-Wilk test\n"
            "3. Homoscedasticity: scale-location plot, Breusch-Pagan test\n"
            "4. Independence: Durbin-Watson test (time series)\n"
            "5. Multicollinearity: VIF > 5-10 indicates concern\n"
            "6. Influential points: Cook's distance > 4/n\n"
            "7. Model fit: R-squared, adjusted R-squared, AIC/BIC for comparison\n"
            "Address violations before interpreting coefficients."
        ),
        "importance": 8,
        "tags": ["regression", "diagnostics", "assumptions", "statistics"],
    },
    # ---- A/B Testing ----
    {
        "category": "methodology_note",
        "content": (
            "A/B testing essentials:\n"
            "- Define primary metric and minimum detectable effect (MDE) upfront\n"
            "- Calculate sample size: n = (Z_alpha + Z_beta)^2 * 2 * sigma^2 / delta^2\n"
            "- For proportions: n = (Z_a + Z_b)^2 * (p1*(1-p1) + p2*(1-p2)) / (p1-p2)^2\n"
            "- Run for full duration — no peeking (or use sequential testing)\n"
            "- Check for sample ratio mismatch (SRM) as a validity check\n"
            "- Use Bonferroni or Holm correction for multiple comparisons\n"
            "- Report confidence intervals, not just p-values\n"
            "- Consider practical significance, not just statistical significance"
        ),
        "importance": 8,
        "tags": ["ab-testing", "experiment", "sample-size", "methodology"],
    },
    # ---- Common Pitfalls ----
    {
        "category": "best_practice",
        "content": (
            "Common data analysis pitfalls to avoid:\n"
            "- Simpson's paradox: aggregated trends reverse within subgroups\n"
            "- Survivorship bias: analyzing only successful/surviving cases\n"
            "- p-hacking: testing many hypotheses until one is significant\n"
            "- Confounding: correlation without causation\n"
            "- Overfitting: model performs well on training data but fails on new data\n"
            "- Ecological fallacy: inferring individual behavior from group data\n"
            "- Selection bias: non-random sample doesn't represent population\n"
            "- Multiple testing: increased false positive rate without correction\n"
            "Always pre-register analyses when possible."
        ),
        "importance": 9,
        "tags": ["pitfalls", "bias", "methodology", "best-practices"],
    },
]


def seed_memories(base_url: str, dry_run: bool = False) -> None:
    """Post seed memories to the agent's memory API."""
    url = f"{base_url}/api/memories"
    success = 0
    failed = 0

    for i, memory in enumerate(SEED_MEMORIES, 1):
        if dry_run:
            print(f"  [{i}/{len(SEED_MEMORIES)}] (dry run) {memory['category']}: "
                  f"{memory['content'][:60]}...")
            success += 1
            continue

        try:
            resp = requests.post(url, json=memory, timeout=10)
            if resp.status_code in (200, 201):
                print(f"  [{i}/{len(SEED_MEMORIES)}] Stored: {memory['category']} — "
                      f"{memory['content'][:60]}...")
                success += 1
            else:
                print(f"  [{i}/{len(SEED_MEMORIES)}] FAILED ({resp.status_code}): "
                      f"{memory['category']}")
                failed += 1
        except requests.exceptions.ConnectionError:
            print(f"  [{i}/{len(SEED_MEMORIES)}] CONNECTION ERROR — is the agent running?")
            failed += 1
        except Exception as e:
            print(f"  [{i}/{len(SEED_MEMORIES)}] ERROR: {e}")
            failed += 1

        # Small delay to avoid overwhelming the API
        time.sleep(0.2)

    print(f"\nDone: {success} stored, {failed} failed, {len(SEED_MEMORIES)} total")


def main():
    parser = argparse.ArgumentParser(
        description="Seed foundational memories into the Synapsis Analytics Agent"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:7777",
        help="Base URL of the agent (default: http://localhost:7777)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print memories without sending them",
    )
    args = parser.parse_args()

    print(f"Seeding {len(SEED_MEMORIES)} foundational memories to {args.base_url}")
    print()
    seed_memories(args.base_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
