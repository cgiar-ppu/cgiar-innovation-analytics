# Analytics Best Practices

## Data Quality Checklist
- [ ] Check for missing values (pattern: MCAR, MAR, MNAR?)
- [ ] Identify and handle outliers (IQR, Z-score, domain knowledge)
- [ ] Verify data types (numeric vs categorical, date parsing)
- [ ] Check for duplicates
- [ ] Validate ranges (negative ages, future dates, impossible values)
- [ ] Assess sample size adequacy for planned analyses
- [ ] Document all transformations applied

## Statistical Testing Guide

### Choosing the Right Test
| Scenario | Test |
|----------|------|
| Compare 2 group means (normal) | Independent t-test |
| Compare 2 group means (non-normal) | Mann-Whitney U |
| Compare 2+ group means | One-way ANOVA (+ post-hoc) |
| Compare 2+ group medians | Kruskal-Wallis |
| Before/after (paired, normal) | Paired t-test |
| Before/after (paired, non-normal) | Wilcoxon signed-rank |
| Association (categorical) | Chi-squared / Fisher's exact |
| Correlation (continuous) | Pearson (linear) / Spearman (monotonic) |
| Predict continuous outcome | Linear regression |
| Predict binary outcome | Logistic regression |
| Time-to-event | Cox proportional hazards |

### Effect Size Conventions (Cohen)
| Measure | Small | Medium | Large |
|---------|-------|--------|-------|
| Cohen's d | 0.2 | 0.5 | 0.8 |
| Pearson r | 0.1 | 0.3 | 0.5 |
| Cohen's f | 0.1 | 0.25 | 0.4 |
| Odds Ratio | 1.5 | 2.5 | 4.3 |

## Visualization Guidelines
1. **Choose the right chart type**:
   - Distribution → Histogram, box plot, violin plot
   - Comparison → Bar chart, dot plot
   - Relationship → Scatter plot, heatmap
   - Trend → Line chart, area chart
   - Composition → Stacked bar, pie (sparingly)
2. **Label everything**: Title, axes, units, legend
3. **Use consistent colors** within a report
4. **Avoid 3D charts** — they distort perception
5. **Start y-axis at zero** for bar charts
6. **Use accessible color palettes** (colorblind-safe)
7. **Label provenance on the figure itself:** reporting year(s), geography definition, funding window (W1/W2 vs bilateral), and result type belong in the title or subtitle of every PRMS chart — not only in the surrounding prose. Distinguish the DB snapshot/extract date from the reporting year; they are different things.

## Reporting Standards
1. Report **confidence intervals**, not just p-values
2. Always state **sample size**
3. Include **effect sizes** alongside significance tests
4. Report **assumptions checked** (normality, homoscedasticity, independence)
5. Use **reproducible methods** (save code, note package versions)
6. Distinguish **correlation from causation**
7. Acknowledge **limitations explicitly**
8. **No un-sourced specifics.** Partner names, beneficiary counts, innovation→country pairings, and dollar allocations in any table or recommendation must trace to a retrieved query result. Inferences and extrapolations must be labelled as such, never mixed into a data table as if queried.
