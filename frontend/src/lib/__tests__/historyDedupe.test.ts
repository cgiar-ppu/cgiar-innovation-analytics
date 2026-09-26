/**
 * QA-4 D1: a reopened chat showed every cited answer twice — the `text` row
 * (linked by the server) and the `result` row's `result_text` (the SDK's
 * unlinked copy). The history loader must show the answer once, including for
 * chats stored before the server linked `result_text`.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, dedupeHistoryMessages } from '../api'
import type { ChatMessage } from '../types'

const URL1003 = 'https://reporting.cgiar.org/reports/result-details/1003?phase=6'
const RAW = 'Top result: [R1003] dairy genomics (IRL 9).'
const LINKED = `Top result: [R1003](${URL1003}) dairy genomics (IRL 9).`

function mockHistory(messages: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ session_id: 's1', messages }), { status: 200 })))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getHistory de-duplicates the result_text copy of the answer', () => {
  it('stored UNLINKED result_text (chats saved since 4015c1b) is shown once, linked', async () => {
    mockHistory([
      { type: 'user', content: 'Which innovations…?' },
      { type: 'text', content: LINKED },
      { type: 'result', estimated_cost: 0.1, turns: 3, duration_ms: 1000, result_text: RAW },
    ])
    const { messages } = await api.getHistory('s1')
    const answers = messages.filter((m) => m.role === 'assistant')
    expect(answers).toHaveLength(1)
    expect(answers[0].content).toBe(LINKED)
    expect(messages.some((m) => m.role === 'result')).toBe(true)
  })

  it('linked result_text (after the server fix) is shown once', async () => {
    mockHistory([
      { type: 'user', content: 'q' },
      { type: 'text', content: LINKED },
      { type: 'result', estimated_cost: 0.1, turns: 1, duration_ms: 10, result_text: LINKED },
    ])
    const { messages } = await api.getHistory('s1')
    expect(messages.filter((m) => m.role === 'assistant')).toHaveLength(1)
  })

  it('result_text that is only the LAST of several text rows is dropped too', async () => {
    mockHistory([
      { type: 'user', content: 'q' },
      { type: 'text', content: 'Let me query PRMS.' },
      { type: 'tool_use', tool: 'mcp__synapsis__prms_query', input: {}, tool_use_id: 't1' },
      { type: 'tool_result', content: '[]', tool_use_id: 't1' },
      { type: 'text', content: LINKED },
      { type: 'result', turns: 2, duration_ms: 10, result_text: RAW.replace('dairy', 'Dairy') + '\n' },
    ])
    const { messages } = await api.getHistory('s1')
    const answers = messages.filter((m) => m.role === 'assistant').map((m) => m.content)
    expect(answers).toEqual(['Let me query PRMS.', LINKED])
  })

  it('slash-command output without streamed text is still shown', async () => {
    mockHistory([
      { type: 'user', content: '/usage' },
      { type: 'result', turns: 0, duration_ms: 5, result_text: 'Usage: 3 turns today' },
      { type: 'user', content: 'next question' },
      { type: 'text', content: LINKED },
      { type: 'result', turns: 1, duration_ms: 5, result_text: RAW },
    ])
    const { messages } = await api.getHistory('s1')
    const answers = messages.filter((m) => m.role === 'assistant').map((m) => m.content)
    expect(answers).toEqual(['Usage: 3 turns today', LINKED])
  })
})

describe('dedupeHistoryMessages', () => {
  const m = (id: string, role: ChatMessage['role'], content: string): ChatMessage =>
    ({ id, role, content, timestamp: 0 }) as ChatMessage

  it('keeps a result_text in a turn whose only assistant row is empty', () => {
    const out = dedupeHistoryMessages([m('hist-0', 'user', 'q'), m('hist-1', 'assistant', '  '), m('hist-2-rt', 'assistant', 'Answer')])
    expect(out.map((x) => x.id)).toEqual(['hist-0', 'hist-1', 'hist-2-rt'])
  })
})
