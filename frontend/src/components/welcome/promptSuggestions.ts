/**
 * @file promptSuggestions.ts
 *
 * The pool of example prompts offered on the welcome screen.
 *
 * Why a pool: the welcome screen used to ship a FIXED array of four examples,
 * so every user on every load saw the same four cards ("always the same; want
 * diversity" — Marc Schut feedback item F10). The screen now samples a subset
 * from this pool at mount, so repeat visits surface different entry points into
 * the data.
 *
 * Content rules (deliberate, do not relax without a data-guide check):
 *
 * 1. Every prompt must be answerable from the PRMS snapshot the agent queries —
 *    reporting years 2022–2025, countries, science programmes / initiatives,
 *    innovation readiness levels, W1/W2 vs W3/bilateral funding, innovations in
 *    use, and the export formats the tool actually produces.
 * 2. NO bare counting questions. `references/prms_data_guide.md` §4 is explicit
 *    that a headline count is meaningless without a stated method, so every
 *    counting prompt here names its slice (a year, a country, a programme) or
 *    asks the agent to state the method it used. "How many innovations are
 *    there?" is exactly the prompt this pool must not contain.
 * 3. Era hygiene: prompts that name a portfolio entity use SP-codes for 2025+
 *    and INIT-codes for 2022–2024, never mixing the two eras under one noun.
 */

import {
  BarChart3,
  Coins,
  Database,
  FileDown,
  Gauge,
  GitCompare,
  Globe2,
  Layers,
  MapPin,
  Search,
  Sprout,
  TrendingUp,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/** Visual theme keys — the colour/gradient families the cards can take. */
export type SuggestionTheme = 'green' | 'blue' | 'lime' | 'orange' | 'teal'

interface ThemeTokens {
  gradient: string
  iconColor: string
  accentColor: string
}

/** CGIAR palette, unchanged from the original four hard-coded cards. */
export const SUGGESTION_THEMES: Record<SuggestionTheme, ThemeTokens> = {
  green: {
    gradient: 'from-[#427730]/15 to-[#7AB800]/10',
    iconColor: 'text-[#427730]',
    accentColor: '#427730',
  },
  blue: {
    gradient: 'from-[#0065BD]/10 to-[#4da3e8]/10',
    iconColor: 'text-[#0065BD]',
    accentColor: '#0065BD',
  },
  lime: {
    gradient: 'from-[#7AB800]/10 to-[#739600]/10',
    iconColor: 'text-[#7AB800]',
    accentColor: '#7AB800',
  },
  orange: {
    gradient: 'from-[#E37222]/10 to-[#FDC82F]/10',
    iconColor: 'text-[#E37222]',
    accentColor: '#E37222',
  },
  teal: {
    gradient: 'from-[#00A19A]/12 to-[#7AB800]/10',
    iconColor: 'text-[#00A19A]',
    accentColor: '#00A19A',
  },
}

export interface PromptSuggestion {
  /** Stable identifier — used as the React key and in tests. */
  id: string
  /** Short card heading. */
  title: string
  /** One-line explanation of what the prompt does. */
  description: string
  /** The text sent to the agent when the card is clicked. */
  prompt: string
  icon: LucideIcon
  theme: SuggestionTheme
}

/**
 * The full suggestion pool (22 entries).
 *
 * The first four entries are the originals that shipped before F10, kept so the
 * pre-existing examples remain reachable; the rest broaden coverage across
 * geography, readiness, funding source, portfolio entities, trends and exports.
 */
export const PROMPT_SUGGESTIONS: PromptSuggestion[] = [
  // -- Originals (reworded only where the data guide required a stated slice) --
  {
    id: 'innovation-search',
    title: 'Innovation Search',
    description: 'Find and explore CGIAR innovations across regions and themes',
    prompt:
      'Show me innovations reported in 2025 on climate-smart agriculture in sub-Saharan Africa, with their result codes and readiness levels.',
    icon: Search,
    theme: 'green',
  },
  {
    id: 'prms-query',
    title: 'PRMS Query',
    description: 'Query the Performance & Results Management System directly',
    prompt:
      'Query the PRMS database for all innovations reported in 2024, broken down by science programme, and state the counting method you used.',
    icon: Database,
    theme: 'blue',
  },
  {
    id: 'regional-analysis',
    title: 'Regional Analysis',
    description: 'Analyse innovation activity by region or country',
    prompt:
      'Analyse CGIAR innovations in South Asia in 2025, broken down by country and readiness level.',
    icon: Globe2,
    theme: 'lime',
  },
  {
    id: 'portfolio-trend',
    title: 'Portfolio Trend',
    description: 'Track how the innovation portfolio has moved year on year',
    prompt:
      'How has the number of innovation developments changed from 2022 to 2025? Show the trend by reporting year and state the method.',
    icon: TrendingUp,
    theme: 'orange',
  },

  // -- Readiness (IRL) --
  {
    id: 'irl-breakdown-year',
    title: 'Readiness Breakdown',
    description: 'See where the portfolio sits on the readiness scale',
    prompt:
      'Break down the innovations reported in 2024 by innovation readiness level (IRL), and say how many carry no readiness record.',
    icon: Gauge,
    theme: 'orange',
  },
  {
    id: 'irl-proven',
    title: 'Proven Innovations',
    description: 'Surface the most mature end of the portfolio',
    prompt:
      'Which innovations reached readiness level 8 or 9 in 2025? List their result codes, titles and reporting programme.',
    icon: Gauge,
    theme: 'green',
  },
  {
    id: 'irl-country',
    title: 'Readiness by Country',
    description: 'Compare maturity across a single country’s portfolio',
    prompt:
      'Break down Kenya’s innovations reported in 2024 by readiness level, counting each result code once.',
    icon: Gauge,
    theme: 'teal',
  },

  // -- Geography --
  {
    id: 'top-countries',
    title: 'Top Countries',
    description: 'Rank the countries the portfolio reaches',
    prompt:
      'Which countries have the most innovations reported in 2024? Give me the top 10 with counts and state the counting method.',
    icon: MapPin,
    theme: 'lime',
  },
  {
    id: 'country-deep-dive',
    title: 'Country Deep Dive',
    description: 'Profile one country across programmes and readiness',
    prompt:
      'Profile the innovations reported in Ethiopia in 2025: which science programmes reported them, and what readiness levels do they sit at?',
    icon: MapPin,
    theme: 'blue',
  },
  {
    id: 'country-trend',
    title: 'Country Trend',
    description: 'Follow one country across the reporting years',
    prompt:
      'Show the year-on-year change in innovations reported in India between 2022 and 2025, counting distinct result codes per year.',
    icon: TrendingUp,
    theme: 'teal',
  },
  {
    id: 'region-programmes',
    title: 'Regional Leaders',
    description: 'See which programmes are most active in a region',
    prompt:
      'Which science programmes reported the most innovations in West Africa in 2025? Show the top five with counts.',
    icon: Globe2,
    theme: 'green',
  },

  // -- Programmes / initiatives --
  {
    id: 'programme-portfolio',
    title: 'Programme Portfolio',
    description: 'List what a single science programme reported',
    prompt:
      'List the innovations reported by SP09 (Scaling for Impact) in 2025 with their result codes and readiness levels.',
    icon: Layers,
    theme: 'blue',
  },
  {
    id: 'programme-compare',
    title: 'Programme Comparison',
    description: 'Put two science programmes side by side',
    prompt:
      'Compare the 2025 innovation portfolios of SP01 (Breeding for Tomorrow) and SP02 (Sustainable Farming) by count and readiness level.',
    icon: GitCompare,
    theme: 'orange',
  },
  {
    id: 'initiative-era',
    title: 'Initiative Era',
    description: 'Look at the 2022–2024 initiative portfolio on its own terms',
    prompt:
      'Which initiatives (the 2022–2024 portfolio era) contributed the most innovations in 2023? Show the top 10 and keep the two portfolio eras separate.',
    icon: Layers,
    theme: 'lime',
  },
  {
    id: 'programme-countries',
    title: 'Programme Reach',
    description: 'Map one programme’s geographic footprint',
    prompt:
      'In how many countries did SP03 (Sustainable Animal and Aquatic Foods) report innovations in 2025? List the countries with counts.',
    icon: Globe2,
    theme: 'teal',
  },

  // -- Funding source --
  {
    id: 'funding-split',
    title: 'Funding Split',
    description: 'Separate pooled W1/W2 from W3/bilateral reporting',
    prompt:
      'Compare W1/W2 pooled versus W3/bilateral innovations reported in 2025, and explain why the two are reported differently.',
    icon: Coins,
    theme: 'orange',
  },
  {
    id: 'bilateral-only',
    title: 'Bilateral View',
    description: 'Isolate the W3/bilateral contribution',
    prompt:
      'How many innovations reported in 2025 come from W3/bilateral funding, and which programmes reported them?',
    icon: Coins,
    theme: 'blue',
  },

  // -- Result types / portfolio composition --
  {
    id: 'innovations-in-use',
    title: 'Innovations in Use',
    description: 'Track the uptake side of the portfolio',
    prompt:
      'How many innovations were in use in 2024 compared with 2025, counted by distinct result code? Show the top 10 countries for 2024.',
    icon: Sprout,
    theme: 'green',
  },
  {
    id: 'portfolio-composition',
    title: 'Portfolio Composition',
    description: 'See the mix of result types behind the headline',
    prompt:
      'Break the 2025 portfolio down by result type (innovation developments, innovations in use, innovation packages) and state the method for each.',
    icon: BarChart3,
    theme: 'lime',
  },
  {
    id: 'impact-areas',
    title: 'Impact Areas',
    description: 'Group the portfolio by impact area',
    prompt:
      'Break the 2025 innovations down by impact area, and say explicitly which tagging system you used.',
    icon: BarChart3,
    theme: 'teal',
  },
  {
    id: 'stated-total',
    title: 'Portfolio Total',
    description: 'Get a headline number with its method attached',
    prompt:
      'What is the total number of distinct innovations reported in 2025, counting each result code once? State the method and the data snapshot.',
    icon: Database,
    theme: 'orange',
  },

  // -- Deliverables --
  {
    id: 'export-briefing',
    title: 'Export a Briefing',
    description: 'Turn an answer into a shareable document',
    prompt:
      'Draft a short briefing on the 2025 innovation portfolio in East Africa — counts, leading programmes and readiness mix — and export it as a Word document.',
    icon: FileDown,
    theme: 'blue',
  },
]

/** How many suggestion cards the welcome screen shows at once. */
export const SUGGESTIONS_SHOWN = 4

/**
 * Sample `count` distinct suggestions from `pool`.
 *
 * Partial Fisher–Yates over a copy: uniform, no duplicates, and it never
 * mutates the shared pool. `rng` is injectable so tests can be deterministic;
 * the app passes nothing and gets `Math.random` (this is UI variety, not a
 * workflow script, so an unseeded RNG is the right call here).
 *
 * Asking for more than the pool holds returns the whole pool, shuffled.
 */
export function pickSuggestions(
  count: number = SUGGESTIONS_SHOWN,
  pool: PromptSuggestion[] = PROMPT_SUGGESTIONS,
  rng: () => number = Math.random,
): PromptSuggestion[] {
  const items = [...pool]
  const n = Math.max(0, Math.min(Math.floor(count), items.length))
  for (let i = 0; i < n; i++) {
    const j = i + Math.floor(rng() * (items.length - i))
    const safeJ = Math.min(Math.max(j, i), items.length - 1)
    const a = items[i]
    const b = items[safeJ]
    // Both indices are in range by construction; the guard keeps TypeScript's
    // noUncheckedIndexedAccess happy without a non-null assertion.
    if (a && b) {
      items[i] = b
      items[safeJ] = a
    }
  }
  return items.slice(0, n)
}
