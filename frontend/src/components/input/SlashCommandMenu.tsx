/**
 * @file SlashCommandMenu.tsx
 * @module components/input
 *
 * Floating autocomplete dropdown for slash commands. Renders above the chat
 * input showing filtered skills and SDK commands grouped by category.
 */

import { useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { SkillInfo } from '../../lib/types-extended'

interface Props {
  suggestions: SkillInfo[]
  selectedIndex: number
  isVisible: boolean
  onSelect: (suggestion: SkillInfo) => void
}

export function SlashCommandMenu({ suggestions, selectedIndex, isVisible, onSelect }: Props) {
  const listRef = useRef<HTMLDivElement>(null)
  const selectedRef = useRef<HTMLButtonElement>(null)

  // Scroll selected item into view
  useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  // Group suggestions by category
  const skillItems = suggestions.filter((s) => s.category === 'skill')
  const commandItems = suggestions.filter((s) => s.category === 'command')

  const renderItem = (item: SkillInfo, globalIndex: number) => {
    const isSelected = globalIndex === selectedIndex
    const icon = item.category === 'skill' ? '\u26A1' : '/'

    return (
      <button
        key={`${item.category}-${item.name}`}
        ref={isSelected ? selectedRef : undefined}
        onClick={() => onSelect(item)}
        className={`w-full flex items-center gap-3 px-3 py-2 text-sm transition-colors cursor-pointer ${
          isSelected
            ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
            : 'text-[var(--text)] hover:bg-[var(--surface-1)]'
        }`}
      >
        <span className="w-5 text-center flex-shrink-0 text-xs opacity-70">{icon}</span>
        <span className="font-medium flex-shrink-0">/{item.name}</span>
        <span className="text-xs text-[var(--text-muted)] truncate">{item.description}</span>
      </button>
    )
  }

  // Build a flat indexed list for correct global index tracking
  let globalIndex = 0
  const sections: React.ReactNode[] = []

  if (skillItems.length > 0) {
    if (commandItems.length > 0) {
      // Only show headers when both categories are present
      sections.push(
        <div key="skills-header" className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Skills
        </div>
      )
    }
    for (const item of skillItems) {
      sections.push(renderItem(item, globalIndex))
      globalIndex++
    }
  }

  if (commandItems.length > 0) {
    if (skillItems.length > 0) {
      sections.push(
        <div key="commands-header" className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] border-t border-[var(--border)]">
          Commands
        </div>
      )
    }
    for (const item of commandItems) {
      sections.push(renderItem(item, globalIndex))
      globalIndex++
    }
  }

  return (
    <AnimatePresence>
      {isVisible && suggestions.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.15 }}
          className="absolute bottom-full left-0 mb-2 w-full max-w-lg z-50"
        >
          <div
            ref={listRef}
            className="glass-strong rounded-xl border border-[var(--border)] shadow-2xl overflow-hidden"
          >
            <div className="max-h-64 overflow-y-auto py-1">
              {sections}
              {suggestions.length === 0 && (
                <div className="px-3 py-4 text-center text-sm text-[var(--text-muted)]">
                  No matching commands
                </div>
              )}
            </div>

            {/* Footer hint */}
            <div className="flex items-center gap-4 px-3 py-1.5 border-t border-[var(--border)] text-[10px] text-[var(--text-muted)]">
              <span>↑↓ navigate</span>
              <span>↵ select</span>
              <span>esc dismiss</span>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
