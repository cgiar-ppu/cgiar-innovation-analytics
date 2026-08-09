/**
 * @file infoCopy.ts
 *
 * The explainer copy behind each ⓘ button (feedback F15: "tour/information
 * button per functionality").
 *
 * Editorial rules — read before changing a word:
 *
 * 1. SHORT: two to four sentences per topic. These are affordances, not docs.
 * 2. FACTUAL: describe only what the surface actually does today.
 * 3. Consistent with the shipped disclaimer register — the tool is scaffolding
 *    for human judgement, not a substitute for it; answers cite PRMS result
 *    codes; figures should be cross-checked against the official CGIAR Results
 *    Dashboard; exports carry an AI-draft watermark.
 * 4. DO NOT restate or paraphrase the four signed-off watermark constants
 *    (WATERMARK_BANNER, PROVENANCE_NOTICE, SOP_DISCLOSURE, PRODUCT_FOOTER in
 *    synapsis/exporters/watermark.py) or the DisclaimerModal / DisclaimerFooter
 *    legal wording. Point at them; never re-word them.
 * 5. NO CONTACT NAMES OR EMAILS. Jose Luis Berenguer's ruling, 2026-08-09: the
 *    contact route lives on the disclaimer surfaces only. A guard test asserts
 *    this file stays name-free.
 */

export interface InfoTopic {
  /** Stable id — used in test ids and as the React key. */
  id: string
  /** Panel heading, also read out as "About <title>" on the trigger. */
  title: string
  /** One paragraph per array entry. */
  body: readonly string[]
}

export const INFO_TOPICS = {
  chat: {
    id: 'chat',
    title: 'Chat',
    body: [
      'Ask questions about the CGIAR innovation portfolio in plain language. The assistant queries the PRMS snapshot directly and cites the result codes behind its numbers, so every figure can be traced back to a record.',
      'It states the counting method it used, because innovation counts change with the method — a portfolio total and a per-year total answer different questions.',
      'Treat answers as a starting point for your own judgement, and cross-check headline figures against the official CGIAR Results Dashboard before using or citing them.',
    ],
  },
  dashboard: {
    id: 'dashboard',
    title: 'Dashboard',
    body: [
      'A fixed set of portfolio views computed straight from the PRMS snapshot: headline counts, readiness levels, leading science programmes and the countries the portfolio reaches.',
      'Each card and chart states the slice it is showing. Counts are of distinct result codes, so an innovation reported in several countries or several years is still counted once within the selected slice.',
      'The 2022–2024 initiatives and the 2025+ science programmes are two different portfolio eras and are labelled separately rather than merged. Cross-check headline figures against the official CGIAR Results Dashboard.',
    ],
  },
  filters: {
    id: 'filters',
    title: 'Data scope',
    body: [
      'These filters constrain the assistant, not just the view. Whatever you select here is sent with every message, so the answer is computed inside that slice and says which slice it used.',
      'Selecting several years asks for innovations active in ANY of them, deduplicated by result code — so a multi-year total is the union of the single-year sets, never their sum.',
      'With nothing selected the assistant sees the whole portfolio. The active selection is always shown in this bar, so no filter can be in force without you seeing it.',
    ],
  },
  exports: {
    id: 'exports',
    title: 'Exports',
    body: [
      'Downloads the current conversation as Word, PDF, HTML or Markdown. "Detailed export" additionally includes the assistant\'s reasoning and the tool inputs and outputs behind each answer.',
      'Every export carries an AI-draft watermark and provenance notice stating that the content is AI-assisted and requires human review before it is used or published.',
      'Check an export against the result codes it cites before circulating it, and have a human author review it before anything is published.',
    ],
  },
} as const satisfies Record<string, InfoTopic>

export type InfoTopicKey = keyof typeof INFO_TOPICS
