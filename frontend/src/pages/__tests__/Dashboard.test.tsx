/**
 * Dashboard numbers (L2-01, L2-13/L4-02, data notes — 2026-09-26).
 *
 * - While loading: a skeleton, never numbers.
 * - On failure with nothing loaded: "data unavailable — try again", never mock
 *   figures (the removed mock carried the superseded 2,755 / 2,006 / 124).
 * - On success: the header says what each number is (innovations vs innovation
 *   results), the source is CGIAR PRMS Reporting with the snapshot dates, and
 *   the W3/bilateral QA note is reachable where bilateral numbers appear.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { PRMSDashboardData } from '../../lib/types-extended'

const getPRMSStats = vi.fn()

vi.mock('../../services/dashboard', () => ({
  dashboardService: {
    getPRMSStats: (...args: unknown[]) => getPRMSStats(...args),
    // Centre / Program dropdown options (covered in DashboardFilters.test.tsx).
    getFilterOptions: () => Promise.resolve({ centers: [], programs: [], source: 'prms' }),
  },
}))
// Charts are covered elsewhere; keep this test about numbers and wording.
vi.mock('../../components/chat/InteractiveChart', () => ({
  InteractiveChart: ({ data }: { data?: { title?: string } }) => <div data-testid="chart">{data?.title}</div>,
}))

import Dashboard from '../Dashboard'
import { useAppConfigStore } from '../../stores/appConfig'
import type { AppConfig } from '../../lib/types'

const chart = (title: string) => ({ chartType: 'bar', title, data: [], series: [], xAxisKey: 'x' })

function payload(overrides: Partial<PRMSDashboardData> = {}): PRMSDashboardData {
  return {
    kpis: {
      total_results: 1641,
      total_innovations: 1185,
      innovation_uses: 403,
      active_initiatives: 14,
      countries_covered: 113,
      innovation_packages: 53,
      total_innovations_w1w2: 963,
      total_innovations_bilateral: 222,
    },
    charts: {
      results_by_type: chart('Innovations by Type (2025)'),
      top_countries: chart('Top 10 Countries (2025)'),
      irl_distribution: chart('Innovation Readiness Levels (2025)'),
      top_initiatives: chart('Top 10 Science Programs (2025)'),
    } as unknown as PRMSDashboardData['charts'],
    year: 2025,
    years: [2025],
    years_label: '2025',
    last_updated: '2026-09-26T20:00:00Z',
    snapshot: {
      available: true,
      extracted_on: '2026-09-13',
      data_as_of: '2026-09-12',
      result_count: 32203,
      table_count: 203,
      open_phases: [],
      source: 'sqlite',
      label: 'PRMS snapshot 2026-09-13 (data as of 2026-09-12)',
      citation: 'PRMS Database (snapshot 2026-09-13, data as of 2026-09-12)',
    },
    method: {
      data_source: 'Source: CGIAR PRMS Reporting (the Performance and Results Management System).',
      quality_gate: 'Only quality-assured results are counted.',
      bilateral_qa: "W3/bilateral innovations are not QA'd in PRMS. They are quality-assured at Center level only.",
      scope: 'A year selection counts innovations active in that year.',
    },
    kpi_errors: [],
    ...overrides,
  }
}

const renderDashboard = () =>
  render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>
  )

const SUPERSEDED = ['2,755', '2,006', '669']

describe('Dashboard', () => {
  beforeEach(() => {
    getPRMSStats.mockReset()
  })

  it('shows a skeleton, not numbers, while the first fetch is pending', () => {
    getPRMSStats.mockReturnValue(new Promise(() => {}))
    renderDashboard()
    expect(screen.getByTestId('dashboard-loading')).toBeInTheDocument()
    for (const n of SUPERSEDED) expect(screen.queryByText(new RegExp(n))).toBeNull()
  })

  it('shows "data unavailable" (never mock figures) when the fetch fails', async () => {
    getPRMSStats.mockRejectedValue(new Error('503'))
    renderDashboard()
    await screen.findByTestId('dashboard-unavailable')
    expect(screen.getByText(/Dashboard data unavailable — try again/)).toBeInTheDocument()
    for (const n of SUPERSEDED) expect(screen.queryByText(new RegExp(n))).toBeNull()
    expect(screen.queryByTestId('stats-card-unavailable')).toBeNull()

    getPRMSStats.mockResolvedValue(payload())
    fireEvent.click(screen.getByText('Try again'))
    await screen.findByTestId('dashboard-headline')
  })

  it('labels the header numbers for what they are (L2-01)', async () => {
    getPRMSStats.mockResolvedValue(payload())
    renderDashboard()
    const headline = await screen.findByTestId('dashboard-headline')
    expect(headline.textContent).toMatch(/1,185 innovations/)
    expect(headline.textContent).toMatch(/1,641 innovation results \(development, use and packages\)/)
    expect(headline.textContent).not.toMatch(/1,641 innovations/)
  })

  it('names the source and the snapshot dates', async () => {
    getPRMSStats.mockResolvedValue(payload())
    renderDashboard()
    const line = await screen.findByTestId('dashboard-snapshot')
    expect(line.textContent).toMatch(/CGIAR PRMS Reporting/)
    expect(line.textContent).toMatch(/2026-09-13/)
    fireEvent.click(screen.getByTestId('info-button-dashboard-source'))
    const panel = screen.getByTestId('info-panel-dashboard-source')
    expect(panel.textContent).toMatch(/PRMS Reporting/)
    expect(panel.textContent).toMatch(/extracted on 2026-09-13, data as of 2026-09-12/)
  })

  it('offers the W3/bilateral QA note where bilateral numbers appear', async () => {
    getPRMSStats.mockResolvedValue(payload())
    renderDashboard()
    await screen.findByText(/963 W1\/W2 \+ 222 W3\/bilateral/)
    fireEvent.click(screen.getByTestId('info-button-dashboard-bilateral'))
    expect(screen.getByTestId('info-panel-dashboard-bilateral').textContent).toMatch(/not QA'd in PRMS/)
  })

  it('shows a failed KPI as "—", never as 0', async () => {
    const p = payload({ kpi_errors: ['innovation_uses'] })
    p.kpis.innovation_uses = null
    getPRMSStats.mockResolvedValue(p)
    renderDashboard()
    await screen.findByTestId('dashboard-partial')
    expect(screen.getAllByTestId('stats-card-unavailable')).toHaveLength(1)
  })

  it('keeps the last real figures (not mock data) when a refresh fails', async () => {
    getPRMSStats.mockResolvedValueOnce(payload())
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    getPRMSStats.mockRejectedValueOnce(new Error('network'))
    fireEvent.click(screen.getByText('Refresh'))
    await screen.findByTestId('dashboard-stale')
    await waitFor(() => expect(screen.getByTestId('dashboard-headline').textContent).toMatch(/1,185 innovations/))
  })

  it('hides the admin-only "Research Agents" card from researchers (QA-4 D6)', async () => {
    useAppConfigStore.setState({ config: { model_policy: { role: 'researcher' } } as unknown as AppConfig })
    getPRMSStats.mockResolvedValue(payload())
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    expect(screen.queryByText('Research Agents')).toBeNull()
    expect(screen.getByText('New Analysis')).toBeInTheDocument()
  })

  it('keeps the "Research Agents" card for administrators', async () => {
    useAppConfigStore.setState({ config: { model_policy: { role: 'admin' } } as unknown as AppConfig })
    getPRMSStats.mockResolvedValue(payload())
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    expect(screen.getByTestId('quick-action-agents')).toBeInTheDocument()
    useAppConfigStore.setState({ config: null })
  })
})
