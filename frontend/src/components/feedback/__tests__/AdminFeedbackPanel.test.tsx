/** Settings → Feedback: admin only, filters go to the server, CSV download carries the token. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminFeedbackPanel, { ratingLabel } from '../AdminFeedbackPanel'
import { useAuthStore } from '../../../stores/auth'

const item = (over: Record<string, unknown> = {}) => ({
  id: 1, created_at: '2026-10-02T09:15:00+00:00', updated_at: '2026-10-02T09:15:00+00:00', channel: 'chat', rating: -1,
  sentiment: 'negative', comment: 'Missed the 2025 filter', expected: 'Use 2025 only', shared_question: null, shared_answer: null,
  user_email: 'ttl@worldbank.example', user_name: 'Test TTL', role: 'researcher', cohort: 'WB TTLs Oct-2026', session_id: 's', message_id: 'r1',
  model: 'claude-sonnet-5', persona: '', scope: '', app_version: 'abc1234', environment: 'dev', ...over,
})
const list = { environment: 'dev', total: 2, returned: 2, counts: { positive: 1, negative: 1, neutral: 0 }, cohorts: ['WB TTLs Oct-2026'],
  items: [item(), item({ id: 2, channel: 'voice', rating: 4, sentiment: 'positive', comment: 'Great', expected: '', cohort: '', message_id: '' })] }
let urls: string[]

beforeEach(() => {
  urls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(url)
    if (url.includes('format=csv')) return new Response('created_at\n', { headers: { 'content-disposition': 'attachment; filename="ia-feedback-dev-20261002.csv"' } })
    return new Response(JSON.stringify(list), { headers: { 'Content-Type': 'application/json' } })
  }))
})

describe('AdminFeedbackPanel', () => {
  it('renders nothing for non-admins and makes no request', () => {
    useAuthStore.setState({ token: 'jwt', user: { userId: 'r', email: 'r@x', name: 'R', role: 'researcher' } } as never)
    const { container } = render(<AdminFeedbackPanel />)
    expect(container).toBeEmptyDOMElement()
    expect(urls).toEqual([])
  })

  it('lists feedback with counts, cohort and ratings; filters and CSV go to the admin endpoint', async () => {
    useAuthStore.setState({ token: 'jwt', user: { userId: 'a', email: 'a@x', name: 'A', role: 'admin' } } as never)
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:x'); URL.revokeObjectURL = vi.fn()
    render(<AdminFeedbackPanel />)
    expect(await screen.findByTestId('feedback-summary')).toHaveTextContent('2 feedback items · 1 positive · 1 negative · 0 neutral')
    expect(screen.getByText('Missed the 2025 filter')).toBeInTheDocument()
    expect(screen.getByText('Not helpful')).toBeInTheDocument()
    expect(screen.getByText('4/5')).toBeInTheDocument()
    expect(urls[0]).toBe('/api/admin/feedback')

    await user.selectOptions(screen.getByLabelText('Rating'), 'negative')
    await user.selectOptions(screen.getByLabelText('Cohort'), 'WB TTLs Oct-2026')
    await waitFor(() => expect(urls.slice(-1)[0]!).toBe('/api/admin/feedback?rating=negative&cohort=WB+TTLs+Oct-2026'))
    await user.click(screen.getByRole('button', { name: /Download CSV/ }))
    await waitFor(() => expect(urls.slice(-1)[0]!).toBe('/api/admin/feedback?rating=negative&cohort=WB+TTLs+Oct-2026&format=csv'))
    const csvCall = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.slice(-1)[0]!
    expect((csvCall[1].headers as Record<string, string>).Authorization).toBe('Bearer jwt')
  })

  it('labels chat ratings as helpful / not helpful and voice ratings out of five', () => {
    expect(ratingLabel('chat', 1)).toBe('Helpful')
    expect(ratingLabel('chat', -1)).toBe('Not helpful')
    expect(ratingLabel('voice', 3)).toBe('3/5')
  })
})
