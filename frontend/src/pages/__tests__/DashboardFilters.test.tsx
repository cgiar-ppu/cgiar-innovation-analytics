/**
 * Centre + Program/Accelerator filters next to the Years filter (Marc Schut,
 * 2026-10-08): the dropdowns render with their options (programs grouped by
 * portfolio era), a selection re-fetches with `centers` / `programs`, "All …"
 * clears it, and the page states the active scope and the era hint.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { PRMSDashboardData } from '../../lib/types-extended'

const getPRMSStats = vi.fn()
const getFilterOptions = vi.fn()

vi.mock('../../services/dashboard', () => ({
  dashboardService: {
    getPRMSStats: (...args: unknown[]) => getPRMSStats(...args),
    getFilterOptions: () => getFilterOptions(),
  },
}))
vi.mock('../../components/chat/InteractiveChart', () => ({
  InteractiveChart: ({ data }: { data?: { title?: string } }) => <div data-testid="chart">{data?.title}</div>,
}))

import Dashboard from '../Dashboard'
import { selectionLabel } from '../../components/dashboard/FilterMultiSelect'
import { scopeTopic } from '../../components/dashboard/dashboardInfo'

const chart = (title: string) => ({ chartType: 'bar', title, data: [], series: [], xAxisKey: 'x' })

const OPTIONS = {
  centers: [
    { code: 'CENTER-05', acronym: 'CIMMYT', name: 'International Maize and Wheat Improvement Center', label: 'CIMMYT — International Maize and Wheat Improvement Center', results: 438 },
    { code: 'CENTER-11', acronym: 'IITA', name: 'International Institute of Tropical Agriculture', label: 'IITA — International Institute of Tropical Agriculture', results: 460 },
  ],
  programs: [
    { code: 'SP01', label: 'SP01 — Breeding for Tomorrow', era: 'Programs & Accelerators (2025+)', results: 233 },
    { code: 'INIT-01', label: 'INIT-01 — Accelerated Breeding', era: 'Initiatives (2022–2024)', results: 189 },
  ],
  source: 'prms' as const,
}

function payload(overrides: Partial<PRMSDashboardData> = {}): PRMSDashboardData {
  return {
    kpis: {
      total_results: 1641, total_innovations: 1185, innovation_uses: 403, active_initiatives: 14,
      countries_covered: 113, innovation_packages: 53, total_innovations_w1w2: 963, total_innovations_bilateral: 222,
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
    scope_label: '2025',
    filters: { centers: [], programs: [], label: '', era_hint: '' },
    last_updated: '2026-10-08T20:00:00Z',
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

describe('Dashboard centre / program filters', () => {
  beforeEach(() => {
    getPRMSStats.mockReset()
    getFilterOptions.mockReset()
    getFilterOptions.mockResolvedValue(OPTIONS)
    getPRMSStats.mockResolvedValue(payload())
  })

  it('renders both dropdowns next to the year filter, defaulting to "All"', async () => {
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    expect(screen.getByTestId('dashboard-year-toggle')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('dashboard-centre-toggle')).not.toBeDisabled())
    expect(screen.getByTestId('dashboard-centre-toggle').textContent).toMatch(/All centres/)
    expect(screen.getByTestId('dashboard-program-toggle').textContent).toMatch(/All programs/)
    // First fetch carries no centre/program filter.
    expect(getPRMSStats).toHaveBeenCalledWith([2025], { centers: [], programs: [] })
  })

  it('lists centres with acronym + full name and programs grouped by era (2025+ first)', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByTestId('dashboard-centre-toggle')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('dashboard-centre-toggle'))
    expect(screen.getByTestId('dashboard-centre-menu').textContent).toMatch(/CIMMYT — International Maize/)
    fireEvent.click(screen.getByTestId('dashboard-program-toggle'))
    const groups = screen.getAllByTestId('dashboard-program-group').map((g) => g.textContent)
    expect(groups).toEqual(['Programs & Accelerators (2025+)', 'Initiatives (2022–2024)'])
  })

  it('a selection re-fetches with the filter params; "All" clears it', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByTestId('dashboard-centre-toggle')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('dashboard-centre-toggle'))
    fireEvent.click(screen.getByTestId('dashboard-centre-option-CENTER-05'))
    await waitFor(() =>
      expect(getPRMSStats).toHaveBeenLastCalledWith([2025], { centers: ['CENTER-05'], programs: [] })
    )
    expect(screen.getByTestId('dashboard-centre-toggle').textContent).toMatch(/CIMMYT/)
    fireEvent.mouseDown(document.body) // click outside closes the menu

    await waitFor(() => expect(screen.getByTestId('dashboard-program-toggle')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('dashboard-program-toggle'))
    fireEvent.click(screen.getByTestId('dashboard-program-option-SP01'))
    await waitFor(() =>
      expect(getPRMSStats).toHaveBeenLastCalledWith([2025], { centers: ['CENTER-05'], programs: ['SP01'] })
    )
    fireEvent.mouseDown(document.body)
    expect(screen.queryByTestId('dashboard-program-menu')).toBeNull()

    await waitFor(() => expect(screen.getByTestId('dashboard-centre-toggle')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('dashboard-centre-toggle'))
    fireEvent.click(screen.getByTestId('dashboard-centre-all'))
    await waitFor(() =>
      expect(getPRMSStats).toHaveBeenLastCalledWith([2025], { centers: [], programs: ['SP01'] })
    )
    expect(screen.getByTestId('dashboard-centre-toggle').textContent).toMatch(/All centres/)
  })

  it('states the active scope in the header and explains lead-or-contribute', async () => {
    getPRMSStats.mockResolvedValue(
      payload({
        scope_label: '2025 · Centre: CIMMYT · Program: SP01',
        filters: {
          centers: [{ code: 'CENTER-05', label: 'CIMMYT' }],
          programs: [{ code: 'SP01', label: 'SP01' }],
          label: 'Centre: CIMMYT · Program: SP01',
          era_hint: '',
        },
      })
    )
    renderDashboard()
    const headline = await screen.findByTestId('dashboard-headline')
    expect(headline.textContent).toMatch(/· 2025 · Centre: CIMMYT · Program: SP01 —/)
    const note = screen.getByTestId('dashboard-filter-note')
    expect(note.textContent).toMatch(/led or contributed to by CIMMYT and by SP01/)
    expect(note.textContent).toMatch(/counted once/)
  })

  it('shows the era hint when the program era and the years do not overlap', async () => {
    getPRMSStats.mockResolvedValue(
      payload({
        kpis: { ...payload().kpis, total_results: 0 },
        filters: {
          centers: [],
          programs: [{ code: 'SP01', label: 'SP01' }],
          label: 'Program: SP01',
          era_hint: 'The selected Programs/Accelerators started in 2025.',
        },
      })
    )
    renderDashboard()
    expect(await screen.findByTestId('dashboard-era-hint')).toHaveTextContent(/started in 2025/)
  })

  it('no filter → no filter note (the default view is unchanged)', async () => {
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    expect(screen.queryByTestId('dashboard-filter-note')).toBeNull()
  })

  it('keeps the dropdowns disabled (year filter still works) if options fail to load', async () => {
    getFilterOptions.mockRejectedValue(new Error('503'))
    renderDashboard()
    await screen.findByTestId('dashboard-headline')
    expect(screen.getByTestId('dashboard-centre-toggle')).toBeDisabled()
    expect(screen.getByTestId('dashboard-year-toggle')).not.toBeDisabled()
  })

  it('pill text and info copy', () => {
    const opts = [
      { value: 'A', short: 'CIMMYT', label: '' },
      { value: 'B', short: 'IITA', label: '' },
      { value: 'C', short: 'ILRI', label: '' },
    ]
    expect(selectionLabel([], opts, 'All centres', 'centres')).toBe('All centres')
    expect(selectionLabel(['A'], opts, 'All centres', 'centres')).toBe('CIMMYT')
    expect(selectionLabel(['A', 'B'], opts, 'All centres', 'centres')).toBe('CIMMYT + IITA')
    expect(selectionLabel(['A', 'B', 'C'], opts, 'All centres', 'centres')).toBe('3 centres')
    expect(scopeTopic(null).body.join(' ')).toMatch(/LEAD OR CONTRIBUTE TO.*counted once.*do not add up/)
  })
})
