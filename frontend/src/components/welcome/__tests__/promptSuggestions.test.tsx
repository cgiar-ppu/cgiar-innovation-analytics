/**
 * Tests for the diversified welcome-screen prompt pool (feedback F10).
 *
 * Guards three things:
 *  1. the pool is genuinely a pool (size, unique ids, unique prompts);
 *  2. `pickSuggestions` samples WITHOUT replacement and actually varies;
 *  3. the content rules hold — no bare counting prompts, every prompt names a
 *     slice or asks for a stated method (references/prms_data_guide.md §4).
 */

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  PROMPT_SUGGESTIONS,
  SUGGESTIONS_SHOWN,
  SUGGESTION_THEMES,
  pickSuggestions,
} from '../promptSuggestions'
import { WelcomeScreen } from '../WelcomeScreen'

describe('the suggestion pool', () => {
  it('is much larger than the four cards shown', () => {
    expect(PROMPT_SUGGESTIONS.length).toBeGreaterThanOrEqual(16)
    expect(SUGGESTIONS_SHOWN).toBe(4)
  })

  it('has unique ids and unique prompts', () => {
    const ids = PROMPT_SUGGESTIONS.map((s) => s.id)
    const prompts = PROMPT_SUGGESTIONS.map((s) => s.prompt)
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(prompts).size).toBe(prompts.length)
  })

  it('gives every entry a title, description, icon and known theme', () => {
    for (const s of PROMPT_SUGGESTIONS) {
      expect(s.title.length).toBeGreaterThan(0)
      expect(s.description.length).toBeGreaterThan(0)
      expect(s.icon).toBeTruthy()
      expect(SUGGESTION_THEMES[s.theme]).toBeDefined()
    }
  })

  it('never offers a bare counting prompt', () => {
    // The data guide forbids a headline count with no stated method. Every
    // counting prompt must pin a year, a country/region, a programme, or ask
    // the agent to state its method.
    const anchors = [
      /\b20(22|23|24|25)\b/,
      /\bmethod\b/i,
      /\bbroken down\b/i,
      /\bdistinct result code\b/i,
    ]
    for (const s of PROMPT_SUGGESTIONS) {
      expect(
        anchors.some((re) => re.test(s.prompt)),
        `"${s.prompt}" states no slice or method`,
      ).toBe(true)
      expect(s.prompt).not.toMatch(/^how many innovations are there/i)
    }
  })

  it('only references reporting years the snapshot covers', () => {
    for (const s of PROMPT_SUGGESTIONS) {
      const years = s.prompt.match(/\b(19|20)\d{2}\b/g) ?? []
      for (const y of years) {
        expect(Number(y)).toBeGreaterThanOrEqual(2022)
        expect(Number(y)).toBeLessThanOrEqual(2025)
      }
    }
  })
})

describe('pickSuggestions', () => {
  it('returns the requested number of DISTINCT entries', () => {
    const picked = pickSuggestions(4)
    expect(picked).toHaveLength(4)
    expect(new Set(picked.map((s) => s.id)).size).toBe(4)
  })

  it('only returns members of the pool', () => {
    const ids = new Set(PROMPT_SUGGESTIONS.map((s) => s.id))
    for (const s of pickSuggestions(4)) expect(ids.has(s.id)).toBe(true)
  })

  it('is deterministic for a fixed rng and varies across rngs', () => {
    const rngA = () => 0
    const rngB = () => 0.999999
    const a1 = pickSuggestions(4, PROMPT_SUGGESTIONS, rngA).map((s) => s.id)
    const a2 = pickSuggestions(4, PROMPT_SUGGESTIONS, rngA).map((s) => s.id)
    const b = pickSuggestions(4, PROMPT_SUGGESTIONS, rngB).map((s) => s.id)
    expect(a1).toEqual(a2)
    expect(a1).not.toEqual(b)
  })

  it('actually rotates over repeated draws', () => {
    const seen = new Set<string>()
    for (let i = 0; i < 40; i++) {
      for (const s of pickSuggestions(4)) seen.add(s.id)
    }
    // With 40 draws of 4 from the pool, a fixed array would show exactly 4.
    expect(seen.size).toBeGreaterThan(SUGGESTIONS_SHOWN)
  })

  it('caps at the pool size and never mutates the pool', () => {
    const before = PROMPT_SUGGESTIONS.map((s) => s.id)
    expect(pickSuggestions(999)).toHaveLength(PROMPT_SUGGESTIONS.length)
    expect(pickSuggestions(0)).toHaveLength(0)
    expect(PROMPT_SUGGESTIONS.map((s) => s.id)).toEqual(before)
  })
})

describe('WelcomeScreen', () => {
  it('renders exactly four suggestion cards', () => {
    render(<WelcomeScreen onPromptClick={vi.fn()} />)
    const grid = screen.getByTestId('welcome-suggestions')
    expect(grid.querySelectorAll('button')).toHaveLength(SUGGESTIONS_SHOWN)
  })

  it('sends the full prompt text when a card is clicked', () => {
    const onPromptClick = vi.fn()
    render(<WelcomeScreen onPromptClick={onPromptClick} />)
    const first = screen.getByTestId('welcome-suggestions').querySelector('button')!
    fireEvent.click(first)
    expect(onPromptClick).toHaveBeenCalledTimes(1)
    const sent = onPromptClick.mock.calls[0]?.[0]
    expect(PROMPT_SUGGESTIONS.map((s) => s.prompt)).toContain(sent)
  })

  it('shuffle swaps the visible set', () => {
    // Force a deterministic, order-shifting rng so the assertion cannot flake.
    const values = [0.9, 0.8, 0.7, 0.6, 0.1, 0.2, 0.3, 0.4]
    let i = 0
    const spy = vi
      .spyOn(Math, 'random')
      .mockImplementation(() => values[i++ % values.length] ?? 0)
    try {
      render(<WelcomeScreen onPromptClick={vi.fn()} />)
      const titlesOf = () =>
        Array.from(screen.getByTestId('welcome-suggestions').querySelectorAll('button')).map(
          (b) => b.getAttribute('data-testid'),
        )
      const before = titlesOf()
      fireEvent.click(screen.getByTestId('welcome-shuffle'))
      expect(titlesOf()).not.toEqual(before)
    } finally {
      spy.mockRestore()
    }
  })
})
