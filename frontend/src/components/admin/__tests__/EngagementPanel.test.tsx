/** Engagement read-out over GET /api/admin/engagement (SYN-2305). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import EngagementPanel from '../EngagementPanel'
import { api } from '../../../lib/api'
import type { AdminEngagement } from '../../../lib/types/usage'

const DATA: AdminEngagement = {
  environment: 'dev', generated_at: '2026-10-14T18:00:00+00:00',
  tracking: "First-party, cookieless event log modelled on Umami's open-source event schema",
  telemetry_enabled: true, from: '2026-10-13', to: '2026-10-14', days: 2, events_since: '2026-10-14T10:00:00+00:00',
  totals: { users: 2, visits: 3, page_views: 4, clicks: 9, questions: 5, session_minutes_avg: 6.5, session_minutes_median: 5 },
  daily: [],
  by_user: [
    { user_key: 'u-aaaaaaaaaa', role: 'researcher', cohort: 'Pilot Oct-2026', days_active: 2, questions: 4, cost_usd: 2.1,
      visits: 2, page_views: 3, clicks: 7, session_minutes_avg: 8, session_minutes_total: 16, last_seen: '2026-10-14' },
    { user_key: 'u-bbbbbbbbbb', role: 'admin', cohort: '', days_active: 1, questions: 1, cost_usd: 0.4,
      visits: 1, page_views: 1, clicks: 2, session_minutes_avg: 3.5, session_minutes_total: 3.5, last_seen: '2026-10-13' },
  ],
  by_cohort: [{ cohort: 'Pilot Oct-2026', users: 1, questions: 4, visits: 2, clicks: 7, session_minutes_avg: 8, session_minutes_total: 16 }],
  top_targets: [{ name: 'chat.send', clicks: 5 }, { name: 'chat.new', clicks: 2 }],
}

describe('EngagementPanel', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows totals, cohorts, pseudonymous accounts and top controls', async () => {
    const spy = vi.spyOn(api, 'getAdminEngagement').mockResolvedValue(DATA)
    render(<EngagementPanel days={14} />)
    const totals = await screen.findByTestId('engagement-totals')
    expect(spy).toHaveBeenCalledWith(14)
    expect(totals).toHaveTextContent('Clicks9')
    expect(totals).toHaveTextContent('Avg session6.5 min')
    expect(screen.getByTestId('engagement-cohorts')).toHaveTextContent('Pilot Oct-2026: 1 users · 4 questions · 7 clicks · 8.0 min avg')
    const rows = within(screen.getByTestId('engagement-users')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('u-aaaaaaaaaa')
    expect(rows[0]).toHaveTextContent('$2.10')
    expect(screen.getByTestId('engagement-targets')).toHaveTextContent('chat.send · 5')
    expect(screen.getByText(/modelled on Umami/)).toBeInTheDocument()
  })

  it('downloads the server CSV', async () => {
    vi.spyOn(api, 'getAdminEngagement').mockResolvedValue(DATA)
    const csv = vi.spyOn(api, 'getAdminEngagementCsv').mockResolvedValue(new Blob(['a,b\n'], { type: 'text/csv' }))
    URL.createObjectURL = vi.fn(() => 'blob:csv')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<EngagementPanel days={30} />)
    await screen.findByTestId('engagement-totals')
    await userEvent.setup().click(screen.getByRole('button', { name: /engagement csv/i }))
    expect(csv).toHaveBeenCalledWith(30)
    expect(click).toHaveBeenCalled()
  })

  it('says so when the figures cannot be loaded', async () => {
    vi.spyOn(api, 'getAdminEngagement').mockRejectedValue(new Error('403'))
    render(<EngagementPanel days={14} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be loaded/i)
  })
})
