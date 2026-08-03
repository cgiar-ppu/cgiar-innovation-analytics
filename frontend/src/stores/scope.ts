/**
 * @file scope.ts
 * @module stores
 *
 * Zustand store for the ACTIVE DATA SCOPE — the year and programme/accelerator
 * filters the user sets in the chat surface.
 *
 * This is deliberately not a dashboard filter: the selection is sent with every
 * chat message and the backend renders it into a scope preamble that constrains
 * what the agent queries and forces it to state the slice in its answer
 * (see synapsis/scope.py). Marc Schut's July-7 ask #6.
 *
 * The selection is UI state scoped to the browser session (not persisted to the
 * backend, not per-chat-session): the filter bar shows exactly what is in force
 * for the next message, so there is never a hidden filter.
 */

import { create } from 'zustand'
import { api } from '../lib/api'

/** One selectable programme / accelerator, as returned by /api/scope/options. */
export interface ScopeProgram {
  /** Portfolio code, e.g. "SP09" or "INIT-13". */
  code: string
  /** Display label, e.g. "SP09 — Scaling for Impact". */
  label: string
  /** Portfolio era grouping, e.g. "Programs & Accelerators (2025+)". */
  era: string
}

/** The wire shape sent to the backend with each message. */
export interface ActiveScope {
  years: number[]
  programs: string[]
}

interface ScopeState {
  /** Selected reporting years (empty = no year restriction). */
  years: number[]
  /** Selected programme labels (empty = no programme restriction). */
  programs: string[]

  /** Year values offered by the backend. */
  yearOptions: number[]
  /** Programme values offered by the backend. */
  programOptions: ScopeProgram[]
  /** Whether the options list came from PRMS or the static fallback. */
  optionsSource: 'prms' | 'fallback' | null
  /** True while /api/scope/options is in flight. */
  loadingOptions: boolean
  /** True once an options load has been attempted (success or failure). */
  optionsLoaded: boolean

  /** Fetch the filter options once (no-op if already loaded / in flight). */
  loadOptions: () => Promise<void>
  toggleYear: (year: number) => void
  toggleProgram: (label: string) => void
  clearScope: () => void
  /** True when no filter is set (⇒ the backend adds no preamble at all). */
  isEmpty: () => boolean
  /**
   * The scope object to attach to an outgoing message, or `undefined` when
   * nothing is selected — so an unfiltered conversation sends exactly the
   * frame it sent before this feature existed.
   */
  getActiveScope: () => ActiveScope | undefined
}

export const useScopeStore = create<ScopeState>((set, get) => ({
  years: [],
  programs: [],

  yearOptions: [],
  programOptions: [],
  optionsSource: null,
  loadingOptions: false,
  optionsLoaded: false,

  loadOptions: async () => {
    const { loadingOptions, optionsLoaded } = get()
    if (loadingOptions || optionsLoaded) return
    set({ loadingOptions: true })
    try {
      const data = await api.get<{
        years: number[]
        programs: ScopeProgram[]
        source: 'prms' | 'fallback'
      }>('/api/scope/options')
      set({
        yearOptions: data.years ?? [],
        programOptions: data.programs ?? [],
        optionsSource: data.source ?? null,
        loadingOptions: false,
        optionsLoaded: true,
      })
    } catch {
      // Filters are an enhancement — a failed load must never block chatting.
      set({ loadingOptions: false, optionsLoaded: true })
    }
  },

  toggleYear: (year) =>
    set((s) => ({
      years: s.years.includes(year)
        ? s.years.filter((y) => y !== year)
        : [...s.years, year].sort((a, b) => a - b),
    })),

  toggleProgram: (label) =>
    set((s) => ({
      programs: s.programs.includes(label)
        ? s.programs.filter((p) => p !== label)
        : [...s.programs, label],
    })),

  clearScope: () => set({ years: [], programs: [] }),

  isEmpty: () => {
    const { years, programs } = get()
    return years.length === 0 && programs.length === 0
  },

  getActiveScope: () => {
    const { years, programs } = get()
    if (years.length === 0 && programs.length === 0) return undefined
    return { years, programs }
  },
}))
