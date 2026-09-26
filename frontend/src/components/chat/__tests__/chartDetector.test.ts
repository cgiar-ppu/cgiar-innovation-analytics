/**
 * QA-4 D2: raw `<chart>{…}</chart>` JSON was printed under every chart.
 * QA-4 D9: plain markdown tables were auto-charted with raw markdown labels
 * ("**43**", "[R22680](…)") and meaningless IRL-per-result bars.
 */
import { describe, expect, it } from 'vitest'
import { detectChartData, detectCharts, stripInlineMarkdown, stripRenderedChartBlocks } from '../chartDetector'

const PIE = JSON.stringify({
  chartType: 'pie',
  title: 'Kenya IRL 7+',
  data: [
    { irl: 'IRL 9', count: 31, percent: 34.1 },
    { irl: 'IRL 8', count: 23, percent: 25.3 },
  ],
  series: [{ key: 'count' }],
  xAxisKey: 'irl',
})
const BAR = JSON.stringify({ chartType: 'bar', data: [{ c: 'Kenya', n: 5 }, { c: 'Ghana', n: 3 }] })

describe('stripRenderedChartBlocks (D2)', () => {
  it('removes a rendered chart block, including one glued to a table row', () => {
    const msg = `| IRL | Count |\n|---|---|\n| 9 | 31 |<chart>\n${PIE}\n</chart>\n\n### From the PRMS data\nText.`
    const out = stripRenderedChartBlocks(msg)
    expect(out).not.toContain('<chart>')
    expect(out).not.toContain('"chartType"')
    expect(out).toContain('| 9 | 31 |')
    expect(out).toContain('### From the PRMS data')
  })

  it('removes every chart block and renders every one', () => {
    const msg = `Intro\n<chart>${PIE}</chart>\nmiddle\n<chart>${BAR}</chart>\nend`
    expect(detectCharts(msg).map((c) => c.chartType)).toEqual(['pie', 'bar'])
    const out = stripRenderedChartBlocks(msg)
    expect(out).not.toContain('<chart>')
    expect(out).toContain('middle')
  })

  it('keeps a block that does not parse as a chart visible', () => {
    const msg = 'A broken spec follows <chart>{not json}</chart> here.'
    expect(stripRenderedChartBlocks(msg)).toBe(msg)
  })

  it('leaves text without charts untouched', () => {
    expect(stripRenderedChartBlocks('Plain **answer**.')).toBe('Plain **answer**.')
  })
})

describe('markdown-table auto-charts (D9)', () => {
  it('strips markdown from labels and values', () => {
    const md = '| Country | Innovations |\n|---|---|\n| **Kenya** | **43** |\n| [Ghana](https://x.org) | 12 |\n| `Mali` | 7 |\n'
    const chart = detectChartData(md)!
    expect(chart).not.toBeNull()
    expect(chart.data).toEqual([
      { Country: 'Kenya', Innovations: 43 },
      { Country: 'Ghana', Innovations: 12 },
      { Country: 'Mali', Innovations: 7 },
    ])
  })

  it('does not chart IRL per result code', () => {
    const md =
      '| Code | IRL |\n|---|---|\n| [R22680](https://reporting.cgiar.org/reports/result-details/22680?phase=6) | 9 |\n| [R28583](https://reporting.cgiar.org/reports/result-details/28583?phase=6) | 8 |\n| R661 | 9 |\n'
    expect(detectChartData(md)).toBeNull()
  })

  it('does not chart a result list: codes + title + IRL level', () => {
    const md =
      '| Result | Innovation | Readiness level |\n|---|---|---|\n| R1003 | Dairy genomics | 9 |\n| R17 | Yam seed | 7 |\n| R188 | Breeding tools | 8 |\n'
    expect(detectChartData(md)).toBeNull()
  })

  it('does not use a result-code column as the label axis', () => {
    const md = '| R | Count |\n|---|---|\n| R1003 | 4 |\n| R17 | 2 |\n'
    expect(detectChartData(md)).toBeNull()
  })

  it('still charts a normal quantity table (and ignores a year column as a value)', () => {
    const md = '| Region | Year | Innovations |\n|---|---|---|\n| Africa | 2025 | 600 |\n| Asia | 2025 | 400 |\n'
    const chart = detectChartData(md)!
    expect(chart.chartType).toBe('bar')
    expect(chart.xAxisKey).toBe('Region')
    expect(chart.series.map((s) => s.key)).toEqual(['Innovations'])
  })

  it('keeps count headers such as "No. of innovations" and "# results" as values', () => {
    const md = '| Country | No. of innovations | # results |\n|---|---|---|\n| Kenya | 43 | 60 |\n| Ghana | 12 | 20 |\n'
    expect(detectChartData(md)!.series.map((s) => s.key)).toEqual(['No. of innovations', '# results'])
  })

  it('stripInlineMarkdown', () => {
    expect(stripInlineMarkdown('**43**')).toBe('43')
    expect(stripInlineMarkdown('[R22680](R22680)')).toBe('R22680')
    expect(stripInlineMarkdown('*Kenya*')).toBe('Kenya')
    expect(stripInlineMarkdown('snake_case_name')).toBe('snake_case_name')
  })
})
