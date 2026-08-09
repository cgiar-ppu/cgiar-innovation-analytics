/**
 * @file chartDetector.ts
 *
 * Pure utility that inspects message content for chart-compatible data.
 * Returns a typed ChartData object when confident, null otherwise.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SeriesConfig {
  key: string
  label?: string
  color?: string
}

export interface ChartData {
  chartType: 'bar' | 'horizontalBar' | 'stackedBar' | 'line' | 'area' | 'pie' | 'multiBar' | 'stackedArea' | 'scatter'
  title?: string
  description?: string
  xAxisKey?: string
  data: Record<string, unknown>[]
  series: SeriesConfig[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Try to parse a JSON string, returning null on failure. */
function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** True if value looks like a date string (ISO-8601 or common formats). */
function looksLikeDate(value: unknown): boolean {
  if (typeof value !== 'string') return false
  // ISO dates, YYYY-MM, YYYY, Mon YYYY, Q1 2024 etc.
  return /^\d{4}[-/]\d{2}([-/]\d{2})?/.test(value) ||
    /^\d{4}$/.test(value) ||
    /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i.test(value) ||
    /^Q[1-4]\s?\d{4}$/i.test(value)
}

/** Extract all JSON candidates (from code fences, chart tags, or raw) */
function extractJsonCandidates(content: string): string[] {
  const candidates: string[] = []

  // 1. Fenced code blocks (```json ... ``` or ``` ... ```)
  const fenceRe = /```(?:json)?\s*\n([\s\S]*?)```/g
  let m: RegExpExecArray | null
  while ((m = fenceRe.exec(content)) !== null) {
    candidates.push(m[1]!.trim())
  }

  // 2. <chart> tags
  const chartTagRe = /<chart>([\s\S]*?)<\/chart>/g
  while ((m = chartTagRe.exec(content)) !== null) {
    candidates.push(m[1]!.trim())
  }

  // 3. Raw JSON objects/arrays in the content (greedy brace/bracket match)
  const rawRe = /(?:^|\n)\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*(?:\n|$)/g
  while ((m = rawRe.exec(content)) !== null) {
    const raw = m[1]!.trim()
    // Only add if it actually parses and wasn't already captured
    if (safeParse(raw) && !candidates.includes(raw)) {
      candidates.push(raw)
    }
  }

  return candidates
}

// ---------------------------------------------------------------------------
// Strategy A — Explicit chart JSON (has chartType + data fields)
// ---------------------------------------------------------------------------

function tryExplicitChart(parsed: unknown): ChartData | null {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  const obj = parsed as Record<string, unknown>

  if (typeof obj.chartType !== 'string') return null
  if (!Array.isArray(obj.data) || obj.data.length < 2) return null

  const validTypes = ['bar', 'line', 'area', 'pie', 'multiBar', 'stackedArea', 'scatter']
  if (!validTypes.includes(obj.chartType)) return null

  // Ensure data items are objects
  if (!obj.data.every((d: unknown) => d && typeof d === 'object' && !Array.isArray(d))) return null

  // Build series — use provided or infer from first data item
  let series: SeriesConfig[] = []
  if (Array.isArray(obj.series) && obj.series.length > 0) {
    series = (obj.series as Record<string, unknown>[]).map(s => ({
      key: String(s.key ?? s.dataKey ?? ''),
      label: s.label ? String(s.label) : undefined,
      color: s.color ? String(s.color) : undefined,
    })).filter(s => s.key)
  }

  const xAxisKey = typeof obj.xAxisKey === 'string' ? obj.xAxisKey : undefined

  // If no series provided, auto-detect from data
  if (series.length === 0) {
    const sample = obj.data[0] as Record<string, unknown>
    for (const [k, v] of Object.entries(sample)) {
      if (k === xAxisKey) continue
      if (typeof v === 'number') {
        series.push({ key: k })
      }
    }
  }

  if (series.length === 0) return null

  return {
    chartType: obj.chartType as ChartData['chartType'],
    title: typeof obj.title === 'string' ? obj.title : undefined,
    description: typeof obj.description === 'string' ? obj.description : undefined,
    xAxisKey,
    data: obj.data as Record<string, unknown>[],
    series,
  }
}

// ---------------------------------------------------------------------------
// Strategy B — Plain JSON array of objects
// ---------------------------------------------------------------------------

function tryJsonArray(parsed: unknown): ChartData | null {
  if (!Array.isArray(parsed) || parsed.length < 2) return null
  if (!parsed.every((d: unknown) => d && typeof d === 'object' && !Array.isArray(d))) return null

  const sample = parsed[0] as Record<string, unknown>
  const keys = Object.keys(sample)

  // Find candidate x-axis (first string key)
  let xAxisKey: string | undefined
  const numericKeys: string[] = []

  for (const k of keys) {
    const allValues = parsed.map((row: Record<string, unknown>) => row[k])
    const allNumeric = allValues.every((v: unknown) => typeof v === 'number' || (typeof v === 'string' && !isNaN(Number(v)) && v.trim() !== ''))
    const allString = allValues.every((v: unknown) => typeof v === 'string')

    if (!xAxisKey && allString && !allNumeric) {
      xAxisKey = k
    } else if (allNumeric) {
      numericKeys.push(k)
    }
  }

  if (numericKeys.length === 0) return null

  // Convert stringified numbers to actual numbers
  const data = parsed.map((row: Record<string, unknown>) => {
    const out: Record<string, unknown> = {}
    for (const k of keys) {
      if (numericKeys.includes(k) && typeof row[k] === 'string') {
        out[k] = Number(row[k])
      } else {
        out[k] = row[k]
      }
    }
    return out
  })

  const series: SeriesConfig[] = numericKeys.map(k => ({ key: k }))

  // Auto-select chart type
  let chartType: ChartData['chartType'] = 'bar'
  if (xAxisKey) {
    const firstVal = sample[xAxisKey]
    if (looksLikeDate(firstVal)) {
      chartType = series.length > 1 ? 'area' : 'line'
    } else if (data.length >= 8) {
      chartType = 'line'
    }
  }

  return { chartType, xAxisKey, data, series }
}

// ---------------------------------------------------------------------------
// Strategy C — Markdown table with numeric columns
// ---------------------------------------------------------------------------

function tryMarkdownTable(content: string): ChartData | null {
  // Find lines that look like a markdown table
  const lines = content.split('\n')
  const tableLines: string[] = []
  let inTable = false

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      // Skip separator rows (e.g. | --- | --- |)
      if (/^\|[\s-:|]+\|$/.test(trimmed)) {
        inTable = true
        continue
      }
      if (inTable || tableLines.length === 0) {
        tableLines.push(trimmed)
        if (tableLines.length === 1) inTable = false // header, wait for separator
      }
    } else if (inTable) {
      break // table ended
    }
  }

  if (tableLines.length < 3) return null // need header + at least 2 data rows

  const parseRow = (line: string) =>
    line.split('|').map(c => c.trim()).filter(c => c.length > 0)

  const headers = parseRow(tableLines[0]!)
  const rows = tableLines.slice(1).map(parseRow)

  if (headers.length < 2 || rows.length < 2) return null

  // Determine numeric columns
  const numericCols: number[] = []
  const stringCols: number[] = []

  for (let col = 0; col < headers.length; col++) {
    const values = rows.map(r => r[col] ?? '')
    const allNumeric = values.every(v => !isNaN(Number(v.replace(/[,$%]/g, ''))) && v.trim() !== '')
    if (allNumeric) {
      numericCols.push(col)
    } else {
      stringCols.push(col)
    }
  }

  if (numericCols.length === 0 || stringCols.length === 0) return null

  const xAxisCol = stringCols[0]!
  const xAxisKey = headers[xAxisCol]!

  const data = rows.map(row => {
    const obj: Record<string, unknown> = {}
    obj[xAxisKey] = row[xAxisCol] ?? ''
    for (const col of numericCols) {
      obj[headers[col]!] = Number((row[col] ?? '0').replace(/[,$%]/g, ''))
    }
    return obj
  })

  const series: SeriesConfig[] = numericCols.map(col => ({ key: headers[col]! }))

  const chartType: ChartData['chartType'] = data.length >= 8 ? 'line' : 'bar'

  return { chartType, xAxisKey, data, series }
}

// ---------------------------------------------------------------------------
// Main detection entry point
// ---------------------------------------------------------------------------

export function detectChartData(content: string): ChartData | null {
  if (!content || content.length < 20) return null

  try {
    // Strategy A & B: try JSON candidates
    const candidates = extractJsonCandidates(content)
    for (const raw of candidates) {
      const parsed = safeParse(raw)
      if (!parsed) continue

      // A — explicit chart
      const explicit = tryExplicitChart(parsed)
      if (explicit) return explicit

      // B — JSON array
      const arr = tryJsonArray(parsed)
      if (arr) return arr
    }

    // Strategy C: markdown table
    const table = tryMarkdownTable(content)
    if (table) return table
  } catch {
    // Conservative — return null on any error
    return null
  }

  return null
}
