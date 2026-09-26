/**
 * Per-answer feedback (Lane H): shown once per finished answer, keyed r<k>
 * like the server, thumbs up/down + optional comment / "what should it have
 * said?" / opt-in sharing; hidden when the server has feedback switched off.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnswerFeedback, { answerOrdinal } from '../AnswerFeedback'
import { useChatStore } from '../../../stores/chat'
import { useSessionsStore } from '../../../stores/sessions'
import { useAuthStore } from '../../../stores/auth'
import { useFeedbackStore } from '../store'
import type { ChatMessage } from '../../../lib/types'

const m = (id: string, role: ChatMessage['role'], extra: Partial<ChatMessage> = {}): ChatMessage => ({ id, role, content: id, timestamp: 0, ...extra })
const chat: ChatMessage[] = [
  m('u1', 'user'), m('a1', 'assistant'), m('t1', 'tool_use'), m('a1b', 'assistant'), m('res1', 'result'),
  m('u2', 'user'), m('a2', 'assistant'), m('res2', 'result', { isError: true }),
  m('u3', 'user'), m('a3', 'assistant'), m('res3', 'result'),
  m('u4', 'user'), m('a4', 'assistant'),  // still streaming
]

type Call = { url: string; init?: RequestInit }
let calls: Call[]
function mockFetch(handler: (url: string, init?: RequestInit) => { status?: number; body: unknown }) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const { status = 200, body } = handler(url, init)
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  }))
}
const saved = (over: Record<string, unknown> = {}) => ({ id: 7, channel: 'chat', session_id: 's1', message_id: 'r3', rating: 1, comment: '', expected: '', share_answer: false, created_at: 1, updated_at: 1, ...over })

beforeEach(() => {
  vi.unstubAllGlobals()
  useFeedbackStore.getState().reset()
  useAuthStore.setState({ token: 'jwt', user: { userId: 'sso:alice', email: 'a@cgiar.org', name: 'Alice', role: 'researcher' } } as never)
  useSessionsStore.setState({ activeSessionId: 's1' } as never)
  useChatStore.setState({ messages: chat } as never)
})

describe('answerOrdinal', () => {
  it('numbers finished answers like the server (k-th result row) and only on the last text of an answer', () => {
    expect(answerOrdinal(chat, 'a1')).toBeNull()        // more text follows in the same answer
    expect(answerOrdinal(chat, 'a1b')).toBe(1)
    expect(answerOrdinal(chat, 'a2')).toBeNull()        // ended in an error
    expect(answerOrdinal(chat, 'a3')).toBe(3)           // the error result still counts as r2
    expect(answerOrdinal(chat, 'a4')).toBeNull()        // still streaming
    expect(answerOrdinal(chat, 'missing')).toBeNull()
  })
})

describe('AnswerFeedback', () => {
  it('renders only under the last text of a finished answer', async () => {
    mockFetch(() => ({ body: { session_id: 's1', feedback: [] } }))
    const { container: none } = render(<AnswerFeedback messageId="a1" />)
    expect(none).toBeEmptyDOMElement()
    render(<AnswerFeedback messageId="a3" />)
    expect(await screen.findByText('Was this answer helpful?')).toBeInTheDocument()
    await waitFor(() => expect(calls[0]!.url).toBe('/api/feedback?session_id=s1&channel=chat'))
    expect((calls[0]!.init!.headers as Record<string, string>).Authorization).toBe('Bearer jwt')
  })

  it('saves a thumbs-down at once, then optional details including what it should have said and sharing', async () => {
    mockFetch((_url, init) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        return { body: saved({ rating: body.rating, comment: body.comment, expected: body.expected, share_answer: body.share_answer }) }
      }
      return { body: { session_id: 's1', feedback: [] } }
    })
    const user = userEvent.setup()
    render(<AnswerFeedback messageId="a3" />)
    await user.click(await screen.findByRole('button', { name: 'Not helpful' }))
    const first = JSON.parse(String(calls.find(c => c.init?.method === 'POST')!.init!.body))
    expect(first).toEqual({ channel: 'chat', session_id: 's1', message_id: 'r3', rating: -1, comment: '', expected: '', share_answer: false })
    expect(screen.getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'true')

    await user.type(screen.getByLabelText('Comment (optional)'), 'Wrong year')
    await user.type(screen.getByLabelText('What should it have said? (optional)'), '1,185 for 2025')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    const posts = calls.filter(c => c.init?.method === 'POST')
    expect(JSON.parse(String(posts[1]!.init!.body))).toMatchObject({ rating: -1, comment: 'Wrong year', expected: '1,185 for 2025', share_answer: true })
    expect(await screen.findByText('Thanks for your feedback.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Comment (optional)')).toBeNull()
  })

  it('shows existing feedback and keeps the comment when the rating changes; no "should have said" field for helpful', async () => {
    mockFetch((_url, init) => init?.method === 'POST'
      ? { body: saved({ rating: 1, comment: 'Kept' }) }
      : { body: { session_id: 's1', feedback: [saved({ rating: -1, comment: 'Kept' })] } })
    const user = userEvent.setup()
    render(<AnswerFeedback messageId="a3" />)
    expect(await screen.findByText('Your feedback:')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Not helpful' })).toHaveAttribute('aria-pressed', 'true'))
    await user.click(screen.getByRole('button', { name: 'Helpful' }))
    const post = JSON.parse(String(calls.find(c => c.init?.method === 'POST')!.init!.body))
    expect(post).toMatchObject({ rating: 1, comment: 'Kept' })
    expect(screen.queryByLabelText('What should it have said? (optional)')).toBeNull()
  })

  it('hides itself when feedback is switched off on the server', async () => {
    mockFetch(() => ({ status: 404, body: { detail: 'Feedback is not enabled in this environment' } }))
    const { container } = render(<AnswerFeedback messageId="a3" />)
    await waitFor(() => expect(useFeedbackStore.getState().disabled).toBe(true))
    expect(container).toBeEmptyDOMElement()
  })

  it('reports a failed save without losing the widget', async () => {
    mockFetch((_url, init) => init?.method === 'POST'
      ? { status: 404, body: { detail: 'Answer not found' } }
      : { body: { session_id: 's1', feedback: [] } })
    const user = userEvent.setup()
    render(<AnswerFeedback messageId="a3" />)
    await user.click(await screen.findByRole('button', { name: 'Helpful' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Answer not found')
  })
})
