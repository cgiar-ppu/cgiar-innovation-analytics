/**
 * Tests for the active-data-scope store (Marc Schut's July-7 ask #6).
 *
 * The important invariant: with nothing selected, `getActiveScope()` returns
 * `undefined`, so an unfiltered message frame is exactly what it was before
 * the feature existed (and the backend adds no preamble).
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useScopeStore } from '../scope'
import { api } from '../../lib/api'

function resetStore() {
  useScopeStore.setState({
    years: [],
    programs: [],
    yearOptions: [],
    programOptions: [],
    optionsSource: null,
    loadingOptions: false,
    optionsLoaded: false,
  })
}

describe('scope store', () => {
  beforeEach(resetStore)
  afterEach(() => vi.restoreAllMocks())

  it('is empty by default and sends no scope', () => {
    expect(useScopeStore.getState().isEmpty()).toBe(true)
    expect(useScopeStore.getState().getActiveScope()).toBeUndefined()
  })

  it('toggles years on and off, keeping them sorted', () => {
    const { toggleYear } = useScopeStore.getState()
    toggleYear(2025)
    toggleYear(2023)
    expect(useScopeStore.getState().years).toEqual([2023, 2025])

    toggleYear(2023)
    expect(useScopeStore.getState().years).toEqual([2025])
  })

  it('toggles programmes on and off', () => {
    const { toggleProgram } = useScopeStore.getState()
    toggleProgram('SP09 — Scaling for Impact')
    expect(useScopeStore.getState().programs).toEqual(['SP09 — Scaling for Impact'])

    toggleProgram('SP09 — Scaling for Impact')
    expect(useScopeStore.getState().programs).toEqual([])
  })

  it('returns the active scope once something is selected', () => {
    useScopeStore.getState().toggleYear(2024)
    useScopeStore.getState().toggleProgram('SP09 — Scaling for Impact')

    expect(useScopeStore.getState().isEmpty()).toBe(false)
    expect(useScopeStore.getState().getActiveScope()).toEqual({
      years: [2024],
      programs: ['SP09 — Scaling for Impact'],
    })
  })

  it('clearScope removes every filter', () => {
    useScopeStore.getState().toggleYear(2024)
    useScopeStore.getState().toggleProgram('SP01 — Breeding for Tomorrow')
    useScopeStore.getState().clearScope()

    expect(useScopeStore.getState().getActiveScope()).toBeUndefined()
  })

  it('loads options once and caches them', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({
      years: [2022, 2023, 2024, 2025],
      programs: [{ code: 'SP09', label: 'SP09 — Scaling for Impact', era: 'Programs & Accelerators (2025+)' }],
      source: 'prms',
    } as never)

    await useScopeStore.getState().loadOptions()
    await useScopeStore.getState().loadOptions()

    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('/api/scope/options')
    expect(useScopeStore.getState().yearOptions).toEqual([2022, 2023, 2024, 2025])
    expect(useScopeStore.getState().programOptions).toHaveLength(1)
    expect(useScopeStore.getState().optionsSource).toBe('prms')
  })

  it('a failed options load never blocks chatting', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'))

    await useScopeStore.getState().loadOptions()

    expect(useScopeStore.getState().loadingOptions).toBe(false)
    expect(useScopeStore.getState().optionsLoaded).toBe(true)
    expect(useScopeStore.getState().getActiveScope()).toBeUndefined()
  })
})
