/**
 * Tests for the selected-specialist store (feedback F3).
 *
 * The important invariant, and the item's stated acceptance criterion: with
 * nothing selected, `getActivePersona()` returns `undefined`, so the outgoing
 * message frame is exactly what it was before the picker existed (and the
 * backend adds no routing preamble).
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { usePersonaStore } from '../persona'
import type { PersonaOption } from '../persona'
import { api } from '../../lib/api'

const OPTIONS: PersonaOption[] = [
  {
    id: 'prms_data_analyst',
    name: 'PRMS Data Analyst',
    description: 'CGIAR PRMS database specialist.',
    type: 'PRMS Database',
    color: 'hsl(30, 70%, 50%)',
    tags: ['PRMS', 'SQL'],
  },
  {
    id: 'report_generator',
    name: 'Report Generator',
    description: 'Leadership-ready deliverables.',
    type: 'Report Generation',
    color: 'hsl(100, 70%, 50%)',
    tags: ['Reports'],
  },
]

function resetStore() {
  usePersonaStore.setState({
    selected: null,
    options: [],
    loadingOptions: false,
    optionsLoaded: false,
  })
}

describe('persona store', () => {
  beforeEach(resetStore)
  afterEach(() => vi.restoreAllMocks())

  it('defaults to no selection and attaches no agent field', () => {
    expect(usePersonaStore.getState().selected).toBeNull()
    expect(usePersonaStore.getState().isEmpty()).toBe(true)
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
    expect(usePersonaStore.getState().selectedOption()).toBeUndefined()
  })

  it('selects and clears a specialist', () => {
    usePersonaStore.setState({ options: OPTIONS })
    usePersonaStore.getState().selectPersona('prms_data_analyst')
    expect(usePersonaStore.getState().getActivePersona()).toBe('prms_data_analyst')
    expect(usePersonaStore.getState().isEmpty()).toBe(false)
    expect(usePersonaStore.getState().selectedOption()?.name).toBe('PRMS Data Analyst')

    usePersonaStore.getState().clearPersona()
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
  })

  it('selectPersona(null) returns to automatic routing', () => {
    usePersonaStore.setState({ options: OPTIONS, selected: 'report_generator' })
    usePersonaStore.getState().selectPersona(null)
    expect(usePersonaStore.getState().isEmpty()).toBe(true)
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
  })

  it('loads the options from /api/personas exactly once', async () => {
    const spy = vi
      .spyOn(api, 'get')
      .mockResolvedValue({ personas: OPTIONS, default: null } as never)

    await usePersonaStore.getState().loadOptions()
    expect(spy).toHaveBeenCalledWith('/api/personas')
    expect(usePersonaStore.getState().options).toHaveLength(2)

    await usePersonaStore.getState().loadOptions()
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('a failed options load never blocks chatting', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'))
    await usePersonaStore.getState().loadOptions()
    const s = usePersonaStore.getState()
    expect(s.optionsLoaded).toBe(true)
    expect(s.loadingOptions).toBe(false)
    expect(s.options).toEqual([])
    // Still no selection ⇒ still the unchanged default frame.
    expect(s.getActivePersona()).toBeUndefined()
  })
})
