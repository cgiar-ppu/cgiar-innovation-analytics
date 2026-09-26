/** Admin usage panel over Lane D's GET /api/admin/usage (Lane E, 2026-09-26). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UsagePanel, { usageToCsv } from '../UsagePanel'
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
