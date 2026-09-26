/** QA-4 D3: the pie showed "3410%" when the chart data carried a `percent` field. */
import { describe, expect, it } from 'vitest'
import { pieShareLabel } from '../InteractiveChart'

describe('pieShareLabel', () => {
  it('computes each share from the charted values, ignoring an entry percent field', () => {
    const data = [
      { name: 'Innovation development', value: 341, percent: 34.1 },
      { name: 'Innovation use', value: 253, percent: 25.3 },
      { name: 'Packages', value: 407, percent: 40.7 },
    ]
    expect([0, 1, 2].map((i) => pieShareLabel(data, 'value', i))).toEqual(['34%', '25%', '41%'])
  })

  it('works when the charted series itself is the percentage', () => {
    const data = [{ name: 'A', percent: 34.1 }, { name: 'B', percent: 65.9 }]
    expect(pieShareLabel(data, 'percent', 0)).toBe('34%')
    expect(pieShareLabel(data, 'percent', 1)).toBe('66%')
  })

  it('never exceeds 100% and handles empty or zero totals', () => {
    expect(pieShareLabel([{ name: 'A', value: 5 }], 'value', 0)).toBe('100%')
    expect(pieShareLabel([{ name: 'A', value: 0 }], 'value', 0)).toBe('0%')
    expect(pieShareLabel([], 'value', 0)).toBe('0%')
  })
})
