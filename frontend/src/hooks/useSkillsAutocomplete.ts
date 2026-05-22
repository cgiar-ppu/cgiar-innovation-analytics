/**
 * @file useSkillsAutocomplete.ts
 * @module hooks
 *
 * Manages slash-command autocomplete state for the chat input.
 * Fetches skills once on mount, detects "/" at position 0, filters
 * suggestions, and handles keyboard navigation.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../lib/api'
import type { SkillInfo } from '../lib/types-extended'

/** In-memory cache shared across all hook instances. */
let _cachedSkills: SkillInfo[] | null = null

export interface UseSkillsAutocompleteReturn {
  /** Filtered suggestions based on current input. */
  suggestions: SkillInfo[]
  /** Currently highlighted index in the suggestions list. */
  selectedIndex: number
  /** Whether the autocomplete menu should be visible. */
  isVisible: boolean
  /** Call to insert the selected suggestion into the input. Returns the new text. */
  selectSuggestion: (suggestion: SkillInfo) => string
  /**
   * Keyboard event handler — call from the textarea's onKeyDown.
   * Returns true if the event was consumed (caller should preventDefault).
   */
  handleKeyDown: (e: React.KeyboardEvent) => { consumed: boolean; newText?: string }
  /** Update the hook's tracked input text. Call on every text change. */
  updateText: (text: string) => void
}

export function useSkillsAutocomplete(): UseSkillsAutocompleteReturn {
  const [skills, setSkills] = useState<SkillInfo[]>(_cachedSkills ?? [])
  const [query, setQuery] = useState('')
  const [isVisible, setIsVisible] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const textRef = useRef('')

  // Fetch skills once on mount
  useEffect(() => {
    if (_cachedSkills) {
      setSkills(_cachedSkills)
      return
    }
    api.getSkills(true)
      .then((res) => {
        _cachedSkills = res.skills
        setSkills(res.skills)
      })
      .catch(() => {
        // Silently fail — autocomplete just won't have skills
      })
  }, [])

  const suggestions = query
    ? skills.filter((s) =>
        s.name.toLowerCase().includes(query.toLowerCase()) ||
        s.description.toLowerCase().includes(query.toLowerCase())
      )
    : skills

  const updateText = useCallback((text: string) => {
    textRef.current = text
    if (text.startsWith('/')) {
      const afterSlash = text.slice(1)
      // Only show when there's no space yet (still typing the command name)
      if (!afterSlash.includes(' ')) {
        setQuery(afterSlash)
        setIsVisible(true)
        setSelectedIndex(0)
        return
      }
    }
    setIsVisible(false)
    setQuery('')
  }, [])

  const selectSuggestion = useCallback((suggestion: SkillInfo) => {
    const newText = `/${suggestion.name} `
    setIsVisible(false)
    setQuery('')
    return newText
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent): { consumed: boolean; newText?: string } => {
    if (!isVisible || suggestions.length === 0) {
      return { consumed: false }
    }

    if (e.key === 'ArrowDown') {
      setSelectedIndex((i) => Math.min(i + 1, suggestions.length - 1))
      return { consumed: true }
    }

    if (e.key === 'ArrowUp') {
      setSelectedIndex((i) => Math.max(i - 1, 0))
      return { consumed: true }
    }

    if (e.key === 'Tab' || e.key === 'Enter') {
      const selected = suggestions[selectedIndex]
      if (selected) {
        const newText = selectSuggestion(selected)
        return { consumed: true, newText }
      }
    }

    if (e.key === 'Escape') {
      setIsVisible(false)
      return { consumed: true }
    }

    return { consumed: false }
  }, [isVisible, suggestions, selectedIndex, selectSuggestion])

  return {
    suggestions: isVisible ? suggestions : [],
    selectedIndex,
    isVisible: isVisible && suggestions.length > 0,
    selectSuggestion,
    handleKeyDown,
    updateText,
  }
}
