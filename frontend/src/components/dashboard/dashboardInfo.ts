/**
 * @file dashboardInfo.ts
 *
 * The ⓘ explainers on the PRMS dashboard (L2-02 + client data notes, 2026-09-26):
 *
 * - "About these figures": where the data comes from (Allison Poulos, OCS,
 *   18 Sep: "Is it PRMS Reporting?") with the snapshot's extraction and
 *   data-as-of dates, and how the figures are counted.
 * - "Years, centres and programs": why "All years" and "2022–2025" can differ,
 *   and how the Centre / Program/Accelerator filters count (lead OR contribute,
 *   counted once — Marc Schut, 2026-10-08).
 * - "W3/bilateral QA": the different QA approach for bilateral innovations
 *   (Nicoleta Trifa, PPT, 14 Sep).
 *
 * The method sentences come from the backend payload (`method`), so the numbers
 * and their explanation are produced in one place; the fallback copy below is
 * only used if an older backend omits them. Dates are ALWAYS data from the
 * snapshot, never typed here. No contact names or emails (see infoCopy.ts).
 */
import type { InfoTopic } from '../common/infoCopy'
import type { PRMSDashboardData } from '../../lib/types-extended'

export const FALLBACK_METHOD = {
  data_source:
    'Source: CGIAR PRMS Reporting (the Performance and Results Management System). The figures are computed from a published snapshot of the PRMS reporting database.',
  quality_gate:
    "Only quality-assured results are counted: W1/W2 (pooled) results that are 'Quality Assessed' in PRMS, plus W3/bilateral results that are 'Approved'. Each innovation is counted once by its PRMS result code.",
  bilateral_qa:
    "W3/bilateral innovations follow a different QA approach: they are not QA'd in PRMS. They are quality-assured at Center level only, and no further control or check has been done on the bilateral reported innovations.",
  scope:
    "'All years' counts each innovation once, at its latest quality-assured report. Selecting years counts innovations active in any of the selected years.",
  filters:
    'Centre and Program/Accelerator filters keep the results the selected centres or programs LEAD OR CONTRIBUTE TO. A result linked to several selected entities is counted once, so per-centre or per-program numbers do not add up to the portfolio total.',
} as const

/** "Snapshot extracted on 2026-09-13 · data as of 2026-09-12" — from the payload. */
export function snapshotDatesLine(data: PRMSDashboardData | null): string {
  const snap = data?.snapshot
  if (!snap || (!snap.extracted_on && !snap.data_as_of)) {
    return 'Snapshot dates unavailable.'
  }
  const parts: string[] = []
  if (snap.extracted_on) parts.push(`extracted on ${snap.extracted_on}`)
  if (snap.data_as_of) parts.push(`data as of ${snap.data_as_of}`)
  return `PRMS Reporting snapshot ${parts.join(', ')}.`
}

export function aboutFiguresTopic(data: PRMSDashboardData | null): InfoTopic {
  const m = data?.method ?? FALLBACK_METHOD
  return {
    id: 'dashboard-source',
    title: 'About these figures',
    body: [
      m.data_source,
      snapshotDatesLine(data),
      m.quality_gate,
      'Cross-check headline figures against the official CGIAR Results Dashboard before citing them; it shows the W1/W2 (pooled) component.',
    ],
  }
}

export function scopeTopic(data: PRMSDashboardData | null): InfoTopic {
  const m = data?.method ?? FALLBACK_METHOD
  return {
    id: 'dashboard-scope',
    title: 'Years, centres and programs',
    body: [m.scope, m.filters ?? FALLBACK_METHOD.filters],
  }
}

export function bilateralTopic(data: PRMSDashboardData | null): InfoTopic {
  const m = data?.method ?? FALLBACK_METHOD
  return {
    id: 'dashboard-bilateral',
    title: 'W3/bilateral QA',
    body: [
      m.bilateral_qa,
      'They are included by default and always shown separately (W1/W2 + bilateral), so they can be read or left out.',
    ],
  }
}
