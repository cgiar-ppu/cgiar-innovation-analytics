/**
 * Tests for the chat specialist picker (feedback F3).
 *
 * The acceptance criterion is DEFAULT BEHAVIOUR UNCHANGED: the picker opens on
 * "Auto (recommended)", nothing is selected until the user chooses, and the
 * current selection is always visible on the pill.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { PersonaPicker } from '../PersonaPicker'
import { usePersonaStore } from '../../../stores/persona'
import type { PersonaOption } from '../../../stores/persona'
import { api } from '../../../lib/api'

const OPTIONS: PersonaOption[] = [
  {
    id: 'prms_data_analyst',
    name: 'PRMS Data Analyst',
    description: 'CGIAR PRMS database specialist.',
    type: 'PRMS Database',
    color: 'hsl(30, 70%, 50%)',
    tags: ['PRMS'],
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

describe('PersonaPicker', () => {
  beforeEach(() => {
    usePersonaStore.setState({
      selected: null,
      options: [],
      loadingOptions: false,
      optionsLoaded: false,
    })
    vi.spyOn(api, 'get').mockResolvedValue({ personas: OPTIONS, default: null } as never)
  })
  afterEach(() => vi.restoreAllMocks())

  it('shows "Auto" and selects nothing until the user picks', async () => {
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().options).toHaveLength(2))

    expect(screen.getByTestId('persona-toggle')).toHaveTextContent('Auto')
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
    expect(screen.queryByTestId('persona-active-summary')).toBeNull()
  })

  it('marks Auto as the checked option when nothing is selected', async () => {
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().options).toHaveLength(2))
    fireEvent.click(screen.getByTestId('persona-toggle'))

    expect(screen.getByTestId('persona-option-auto')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('persona-option-prms_data_analyst')).toHaveAttribute(
      'aria-checked',
      'false',
    )
  })

  it('selecting a specialist stores it and states it on the pill', async () => {
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().options).toHaveLength(2))

    fireEvent.click(screen.getByTestId('persona-toggle'))
    fireEvent.click(screen.getByTestId('persona-option-prms_data_analyst'))

    expect(usePersonaStore.getState().getActivePersona()).toBe('prms_data_analyst')
    expect(screen.getByTestId('persona-toggle')).toHaveTextContent('PRMS Data Analyst')
    // Menu closes on choice.
    expect(screen.queryByTestId('persona-menu')).toBeNull()
  })

  it('choosing Auto again returns to the unchanged default', async () => {
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().options).toHaveLength(2))

    fireEvent.click(screen.getByTestId('persona-toggle'))
    fireEvent.click(screen.getByTestId('persona-option-report_generator'))
    expect(usePersonaStore.getState().getActivePersona()).toBe('report_generator')

    fireEvent.click(screen.getByTestId('persona-toggle'))
    fireEvent.click(screen.getByTestId('persona-option-auto'))
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
    expect(screen.getByTestId('persona-toggle')).toHaveTextContent('Auto')
  })

  it('is keyboard-dismissable and labelled for screen readers', async () => {
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().options).toHaveLength(2))

    const toggle = screen.getByTestId('persona-toggle')
    expect(toggle).toHaveAttribute('aria-label')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('persona-menu')).toBeNull()
    // Escape dismisses without changing the selection.
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
  })

  it('survives an options-load failure without blocking the chat', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'))
    render(<PersonaPicker />)
    await waitFor(() => expect(usePersonaStore.getState().optionsLoaded).toBe(true))

    fireEvent.click(screen.getByTestId('persona-toggle'))
    expect(screen.getByTestId('persona-menu')).toHaveTextContent('No specialists available')
    expect(usePersonaStore.getState().getActivePersona()).toBeUndefined()
  })
})
