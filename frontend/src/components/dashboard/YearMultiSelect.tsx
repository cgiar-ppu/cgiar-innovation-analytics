/**
 * @file YearMultiSelect.tsx
 *
 * Compact "All years / multiselect" year filter for the Innovation Analytics
 * dashboard (colleague-feedback item F7).
 *
 * This is a DASHBOARD control — unlike ScopeFilterBar (which constrains the
 * chat agent), it only re-slices the PRMS dashboard query. The UI pattern is
 * deliberately mirrored from ScopeFilterBar so the two surfaces feel the same:
 * a pill that always states the active selection, a checkbox menu, and an
 * explicit "All years" escape hatch.
 *
 * Selecting "All years" clears every specific year; ticking a specific year
 * clears "All years". The pill text is the single source of truth for what the
 * dashboard is currently showing.
 */

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'

/** Reporting years the PRMS dashboard accepts. Mirrors _VALID_YEARS. */
export const YEAR_OPTIONS = [2025, 2024, 2023, 2022] as const

/** Human label for a year selection — matches the backend `years_label()`. */
export function yearsLabel(years: number[]): string {
  if (years.length === 0) return 'All years'
  const ordered = [...years].sort((a, b) => a - b)
  if (ordered.length === 1) return String(ordered[0])
  if (ordered[ordered.length - 1]! - ordered[0]! === ordered.length - 1) {
    return `${ordered[0]}–${ordered[ordered.length - 1]}`
  }
  return ordered.join(', ')
}

interface YearMultiSelectProps {
  /** Selected years; empty array means "All years". */
  value: number[]
  onChange: (years: number[]) => void
  disabled?: boolean
}

export default function YearMultiSelect({ value, onChange, disabled }: YearMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const toggleYear = (year: number) => {
    onChange(
      value.includes(year) ? value.filter((y) => y !== year) : [...value, year].sort((a, b) => a - b)
    )
  }

  return (
    <div ref={ref} className="relative" data-testid="dashboard-year-filter">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-[var(--border)] bg-[var(--surface-solid)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[#427730]/40"
        data-testid="dashboard-year-toggle"
      >
        <span className="hidden sm:inline text-[var(--text-muted)]">Years</span>
        <span className="font-medium">{yearsLabel(value)}</span>
        <ChevronDown className="w-3.5 h-3.5 text-[var(--text-muted)]" />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute top-full right-0 mt-1 z-30 w-44 rounded-xl border border-[var(--border)] bg-[var(--surface-solid)] shadow-xl p-1"
          data-testid="dashboard-year-menu"
        >
          <button
            type="button"
            onClick={() => onChange([])}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left hover:bg-[var(--surface-2)] text-[var(--text)]"
            data-testid="dashboard-year-all"
          >
            <span className="w-3.5 shrink-0">
              {value.length === 0 && <Check className="w-3.5 h-3.5 text-[#427730]" />}
            </span>
            All years
          </button>
          <div className="my-1 border-t border-[var(--border)]" />
          {YEAR_OPTIONS.map((y) => (
            <label
              key={y}
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-[var(--surface-2)] text-[var(--text)]"
            >
              <input
                type="checkbox"
                checked={value.includes(y)}
                onChange={() => toggleYear(y)}
                data-testid={`dashboard-year-${y}`}
              />
              {y}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
