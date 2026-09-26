/** QA-4 D2: a message with a <chart> block shows the chart, not its JSON. */
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { AssistantMessage } from '../AssistantMessage'

describe('AssistantMessage with a <chart> block', () => {
  it('does not print the chart spec JSON in the text body', () => {
    const spec = JSON.stringify({ chartType: 'pie', data: [{ n: 'A', v: 1 }, { n: 'B', v: 3 }], series: [{ key: 'v' }] })
    const content = `Here is the split.\n\n<chart>\n${spec}\n</chart>\n\nThe end.`
    const { container } = render(
      <AssistantMessage message={{ id: 'm1', role: 'assistant', content, timestamp: 0 }} />,
    )
    const prose = container.querySelector('.prose')!
    expect(prose.textContent).toContain('Here is the split.')
    expect(prose.textContent).toContain('The end.')
    expect(prose.textContent).not.toContain('chartType')
    expect(container.textContent).toContain('Show raw data')
  })
})
