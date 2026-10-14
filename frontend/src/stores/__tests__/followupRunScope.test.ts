/**
 * Quick follow-up regression (verification round, Oct 2026).
 *
 * A follow-up sent 1-3 s after an answer made the server cancel the previous
 * run while it was still post-processing; that run's late terminal events
 * (task_status, session_complete) arrived after the user's new message and
 * were adopted as the new turn's run id, so every event of the real new run
 * was dropped: empty bubble, spinning stop button, answer only after reload.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../chat'
import { useSessionsStore } from '../sessions'
import { flushStreamingDeltas } from '../chat/messageHandlers'
import { _resetRetiredRuns, isStaleRunEvent, mayBootstrapRun, retireRun } from '../chat/runScope'
import { routeWebSocketMessage } from '../../hooks/wsMessageRouter'
import type { ServerMessage } from '../../lib/types'

vi.mock('../../lib/api', () => ({ api: { getHistory: vi.fn(), listSessions: vi.fn(async () => ({ sessions: [] })) } }))

const SID = 'sess-1'
const ctx = { getLastSessionComplete: () => null, setLastSessionComplete: () => {} }
const route = (m: Record<string, unknown>) => routeWebSocketMessage({ session_id: SID, ...m } as ServerMessage & { session_id: string }, ctx)

function answer(run: string, text: string) {
  route({ type: 'system', subtype: 'init', data: { model: 'm' }, run_id: run })
  route({ type: 'text', content: text, run_id: run })
  flushStreamingDeltas()
  route({ type: 'result', estimated_cost: 0.01, turns: 1, duration_ms: 10, auth_method: 'x', is_error: false, run_id: run })
}

beforeEach(() => {
  _resetRetiredRuns()
  useChatStore.setState({ messages: [], streamingText: '', streamingThinking: '', isBusy: false, cancelled: false, currentRunId: null, replayMode: false })
  useSessionsStore.setState({ activeSessionId: SID })
  useSessionsStore.getState().loadSessions = vi.fn() as never
})

describe('run scoping', () => {
  it('late terminal events of the previous run do not hide the follow-up answer', () => {
    useChatStore.getState().addUserMessage('Q1')
    answer('run-1', 'Answer one.')
    expect(useChatStore.getState().isBusy).toBe(false)

    // The user asks a follow-up straight away …
    useChatStore.getState().addUserMessage('And in 2023?')
    // … and the cancelled previous run reports its end only now.
    route({ type: 'task_status', status: 'cancelled', run_id: 'run-1' })
    route({ type: 'session_complete', run_id: 'run-1' })
    expect(useChatStore.getState().currentRunId).toBeNull()
    expect(useChatStore.getState().isBusy).toBe(true)

    answer('run-2', 'Answer two.')
    const assistant = useChatStore.getState().messages.filter(m => m.role === 'assistant').map(m => m.content)
    expect(assistant).toEqual(['Answer one.', 'Answer two.'])
    expect(useChatStore.getState().currentRunId).toBe('run-2')
    expect(useChatStore.getState().isBusy).toBe(false)
  })

  it('a late text_links of the previous run cannot claim the new turn', () => {
    useChatStore.getState().addUserMessage('Q1')
    answer('run-1', 'R1')
    useChatStore.getState().addUserMessage('Q2')
    route({ type: 'text_links', original: 'R1', content: '[R1](x)', run_id: 'run-1' })
    answer('run-2', 'R2')
    expect(useChatStore.getState().messages.filter(m => m.role === 'assistant').map(m => m.content)).toEqual(['R1', 'R2'])
  })

  it('helpers: retired runs are stale, terminal types never bootstrap', () => {
    retireRun('old')
    expect(isStaleRunEvent('old', null)).toBe(true)
    expect(isStaleRunEvent('new', null)).toBe(false)
    expect(isStaleRunEvent('a', 'b')).toBe(true)
    expect(isStaleRunEvent(undefined, 'b')).toBe(false)
    expect(mayBootstrapRun('text', 'new', null)).toBe(true)
    expect(mayBootstrapRun('task_status', 'new', null)).toBe(false)
    expect(mayBootstrapRun('session_complete', 'new', null)).toBe(false)
    expect(mayBootstrapRun('text', 'old', null)).toBe(false)
    expect(mayBootstrapRun('text', 'new', 'cur')).toBe(false)
  })
})
