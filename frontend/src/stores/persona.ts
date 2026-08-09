/**
 * @file persona.ts
 * @module stores
 *
 * Zustand store for the SELECTED SPECIALIST — the agent the user picks in the
 * chat surface (feedback F3: "can I use a specific agent if I want/need? now I
 * cannot find this option").
 *
 * The selection is sent with every chat message as `agent: "<id>"`; the backend
 * renders it into a routing preamble that tells the orchestrator to delegate
 * this turn to that specialist via the Task tool (see synapsis/persona.py).
 *
 * DEFAULT IS "NO SELECTION" and stays that way until the user picks: with
 * nothing selected, `getActivePersona()` returns undefined and the outgoing
 * frame is byte-identical to the pre-picker one, so the shipped default routing
 * is unchanged.
 *
 * Like the data scope, this is browser-session UI state (not persisted, not
 * per-chat-session) and the picker always shows what is in force, so a turn can
 * never be routed by a preference the user has forgotten about.
 */

import { create } from 'zustand'
import { api } from '../lib/api'

/** One selectable specialist, as returned by GET /api/personas. */
export interface PersonaOption {
  /** Builtin agent id, e.g. "prms_data_analyst". */
  id: string
  /** Display name, e.g. "PRMS Data Analyst". */
  name: string
  /** What the specialist is for (the AgentDefinition's own description). */
  description: string
  /** Short category label, e.g. "PRMS Database". */
  type: string
  /** HSL swatch used as the option's dot. */
  color: string
  tags: string[]
}

interface PersonaState {
  /** The selected agent id, or null for "no preference" (the default). */
  selected: string | null
  /** Specialists offered by the backend. */
  options: PersonaOption[]
  loadingOptions: boolean
  optionsLoaded: boolean

  /** Fetch the picker options once (no-op if already loaded / in flight). */
  loadOptions: () => Promise<void>
  /** Select a specialist (or pass null to go back to automatic routing). */
  selectPersona: (id: string | null) => void
  clearPersona: () => void
  /** The currently selected option object, if any. */
  selectedOption: () => PersonaOption | undefined
  /** True when nothing is selected (⇒ the backend adds no preamble at all). */
  isEmpty: () => boolean
  /**
   * The agent id to attach to an outgoing message, or `undefined` when nothing
   * is selected — so an unpicked conversation sends exactly the frame it sent
   * before this feature existed.
   */
  getActivePersona: () => string | undefined
}

export const usePersonaStore = create<PersonaState>((set, get) => ({
  selected: null,
  options: [],
  loadingOptions: false,
  optionsLoaded: false,

  loadOptions: async () => {
    const { loadingOptions, optionsLoaded } = get()
    if (loadingOptions || optionsLoaded) return
    set({ loadingOptions: true })
    try {
      const data = await api.get<{ personas: PersonaOption[]; default: string | null }>(
        '/api/personas',
      )
      set({
        options: data.personas ?? [],
        loadingOptions: false,
        optionsLoaded: true,
      })
    } catch {
      // The picker is an enhancement — a failed load must never block chatting.
      set({ loadingOptions: false, optionsLoaded: true })
    }
  },

  selectPersona: (id) => set({ selected: id }),

  clearPersona: () => set({ selected: null }),

  selectedOption: () => {
    const { selected, options } = get()
    if (!selected) return undefined
    return options.find((p) => p.id === selected)
  },

  isEmpty: () => !get().selected,

  getActivePersona: () => get().selected ?? undefined,
}))
