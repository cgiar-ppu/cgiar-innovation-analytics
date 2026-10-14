/** Admin usage panel over Lane D's GET /api/admin/usage (Lane E, 2026-09-26). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UsagePanel, { usageToCsv } from '../UsagePanel'

// The engagement section has its own tests (EngagementPanel.test.tsx).
vi.mock('../EngagementPanel', () => ({ default: () => null }))
import { api } from '../../../lib/api'
import type { AdminUsage } from '../../../lib/types/usage'

const policy = { role: 'researcher', default_model: 'claude-sonnet-5', allowed_models: ['claude-sonnet-5'],
  max_budget_usd_per_turn: 1, daily_budget_usd: 5, max_turns: 60, show_cost: false }

const USAGE: AdminUsage = {
  environment: 'dev', git_sha: 'abc1234', generated_at: '2026-09-26T21:00:00+00:00', currency: 'USD',
  cost_basis: 'Model cost as reported by the Claude Agent SDK per question (list prices).',
  policy: { researcher: policy, admin: { ...policy, role: 'admin', show_cost: true } },
  days: 2, ledger_since: '2026-09-26',
  totals: { turns: 5, sessions: 3, users: 2, cost_usd: 1.25, errors: 0, voice_sessions: 1, voice_minutes: 3.5 },
  daily: [
    { date: '2026-09-25', turns: 2, sessions: 1, users: 1, cost_usd: 0.5, errors: 0,
      by_role: { researcher: { turns: 2, cost_usd: 0.5, users: 1 } },
      by_model: { 'claude-sonnet-5': { turns: 2, cost_usd: 0.5 } }, voice: { sessions: 0, minutes: 0 }, source: 'estimated' },
    { date: '2026-09-26', turns: 3, sessions: 2, users: 2, cost_usd: 0.75, errors: 0,
      by_role: { admin: { turns: 1, cost_usd: 0.6, users: 1 }, researcher: { turns: 2, cost_usd: 0.15, users: 1 } },
      by_model: { 'claude-opus-5-5': { turns: 1, cost_usd: 0.6 }, 'claude-sonnet-5': { turns: 2, cost_usd: 0.15 } },
      voice: { sessions: 1, minutes: 3.5 }, source: 'recorded' },
  ],
}

describe('UsagePanel', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('shows totals and one row per day, newest first', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue(USAGE)
    render(<UsagePanel />)
    const totals = await screen.findByTestId('usage-totals')
    expect(totals).toHaveTextContent('Questions5')
    expect(totals).toHaveTextContent('$1.25')
    expect(totals).toHaveTextContent('3.5 min')
    const rows = within(screen.getByTestId('usage-table')).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.firstChild?.textContent)).toEqual(['2026-09-26', '2026-09-25'])
    expect(rows[0]).toHaveTextContent('admin $0.60')
    expect(rows[0]).toHaveTextContent('recorded')
    expect(screen.getByText('dev')).toBeInTheDocument()
  })

  it('re-queries when the period changes', async () => {
    const spy = vi.spyOn(api, 'getAdminUsage').mockResolvedValue(USAGE)
    render(<UsagePanel />)
    await screen.findByTestId('usage-totals')
    await userEvent.setup().selectOptions(screen.getByLabelText('Period'), '30')
    expect(spy).toHaveBeenLastCalledWith(30)
  })

  it('says so when the figures cannot be loaded (e.g. 403)', async () => {
    vi.spyOn(api, 'getAdminUsage').mockRejectedValue(new Error('GET /api/admin/usage: 403'))
    render(<UsagePanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be loaded/i)
  })

  it('downloads a CSV of the loaded figures', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue(USAGE)
    const created: Blob[] = []
    URL.createObjectURL = vi.fn((b: Blob) => { created.push(b); return 'blob:csv' })
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<UsagePanel />)
    await screen.findByTestId('usage-totals')
    await userEvent.setup().click(screen.getByRole('button', { name: /csv/i }))
    expect(click).toHaveBeenCalled()
    expect(created[0]!.type).toMatch(/text\/csv/)
  })
})

describe('usageToCsv', () => {
  it('has one row per day with per-role and per-model columns', () => {
    const lines = usageToCsv(USAGE).trim().split('\n')
    expect(lines).toHaveLength(3)
    const header = lines[0]!.split(',')
    expect(header.slice(0, 7)).toEqual(['environment', 'date', 'questions', 'chats', 'users', 'cost_usd', 'errors'])
    expect(header).toContain('cost_usd_admin')
    expect(header).toContain('questions_claude-opus-5-5')
    expect(header.slice(-3)).toEqual(['voice_sessions', 'voice_minutes', 'source'])
    const today = lines[2]!.split(',')
    expect(today[0]).toBe('dev')
    expect(today[1]).toBe('2026-09-26')
    expect(today[header.indexOf('cost_usd_admin')]).toBe('0.6000')
    expect(lines[1]!.split(',')[header.indexOf('cost_usd_admin')]).toBe('0.0000')
  })
})

describe('cohort split (QA-4 D14)', () => {
  const WITH_COHORTS: AdminUsage = {
    ...USAGE,
    daily: [
      { ...USAGE.daily[0]!, by_cohort: { 'WB TTLs Oct-2026': { turns: 1, cost_usd: 0.2, users: 1 } } },
      { ...USAGE.daily[1]!, by_cohort: { 'WB TTLs Oct-2026': { turns: 2, cost_usd: 0.4, users: 1 },
        'QA4 cohort Sep-2026': { turns: 1, cost_usd: 0.044, users: 1 } } },
    ],
  }

  beforeEach(() => vi.restoreAllMocks())

  it('shows per-cohort totals for the period and per day', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue(WITH_COHORTS)
    render(<UsagePanel />)
    const box = await screen.findByTestId('usage-cohorts')
    expect(box).toHaveTextContent('WB TTLs Oct-2026: 3 questions · $0.60')
    expect(box).toHaveTextContent('QA4 cohort Sep-2026: 1 questions · $0.04')
    const rows = within(screen.getByTestId('usage-table')).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('QA4 cohort Sep-2026 1 · $0.04')
  })

  it('shows no cohort box when nobody from a cohort used the app', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue(USAGE)
    render(<UsagePanel />)
    await screen.findByTestId('usage-totals')
    expect(screen.queryByTestId('usage-cohorts')).toBeNull()
  })

  it('adds per-cohort CSV columns', () => {
    const header = usageToCsv(WITH_COHORTS).split('\n')[0]!
    expect(header).toContain('questions_cohort_QA4 cohort Sep-2026')
    expect(header).toContain('cost_usd_cohort_WB TTLs Oct-2026')
  })
})

describe('MVP test budget card (SYN-2306)', () => {
  beforeEach(() => vi.restoreAllMocks())

  const BUDGET = {
    enabled: true, budget_usd: 5000, spent_usd: 3812.5, remaining_usd: 1187.5, pct: 76.25, state: 'open',
    window: { start: '2026-10-15T08:00:00+00:00', end: '2026-11-14T08:00:00+00:00', start_source: 'first_run',
      end_source: 'start+30d', days_left: 12.5 },
    thresholds: [50, 75, 90],
    alerts: [{ pct: 50, fraction: 0.5, spent_usd: 2501, crossed_at: '2026-10-25T10:00:00+00:00' },
      { pct: 75, fraction: 0.75, spent_usd: 3751, crossed_at: '2026-11-01T10:00:00+00:00' }],
    session_budget_usd: 3, questions: 7000, voice: { minutes: 0, usd: 0, usd_per_minute: 0.1 }, basis: 'x',
  }

  it('shows spent vs budget, window, crossed thresholds and the per-chat limit', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue({ ...USAGE, test_budget: BUDGET })
    render(<UsagePanel />)
    const card = await screen.findByTestId('test-budget')
    expect(card).toHaveTextContent('Test budget: $3812.50 of $5000.00 (76.3%)')
    expect(card).toHaveTextContent('2026-10-15 to 2026-11-14 (12.5 days left)')
    expect(card).toHaveTextContent('50% (crossed), 75% (crossed), 90%')
    expect(card).toHaveTextContent('Per-chat limit $3.00')
    expect(card).toHaveTextContent('Open')
  })

  it('names the paused state and hides the card when no budget is set', async () => {
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue({ ...USAGE, test_budget: { ...BUDGET, state: 'exhausted', pct: 100.4 } })
    const { unmount } = render(<UsagePanel />)
    expect(await screen.findByTestId('test-budget')).toHaveTextContent('Budget used up - non-admins paused')
    unmount()
    vi.spyOn(api, 'getAdminUsage').mockResolvedValue({ ...USAGE, test_budget: { ...BUDGET, enabled: false, state: 'disabled' } })
    render(<UsagePanel />)
    await screen.findByTestId('usage-totals')
    expect(screen.queryByTestId('test-budget')).toBeNull()
  })
})
