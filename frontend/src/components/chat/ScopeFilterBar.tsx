/**
 * @file ScopeFilterBar.tsx
 *
 * Compact year + programme/accelerator filter for the chat surface.
 *
 * These filters are NOT a dashboard control: whatever is selected here is sent
 * with every chat message and constrains the AGENT — the backend renders it
 * into a scope preamble that tells the agent to restrict its PRMS queries and
 * to state the active slice in its answer (synapsis/scope.py). Marc Schut's
 * July-7 ask #6.
 *
 * The active scope is always visible as pills in the bar, so a filtered answer
 * can never come from a filter the user has forgotten about.
 */

import { useEffect, useRef, useState } from 'react'
import { Filter, X, ChevronDown } from 'lucide-react'
import { useScopeStore } from '../../stores/scope'
import { InfoPopover } from '../common/InfoPopover'
import { INFO_TOPICS } from '../common/infoCopy'

function useClickOutside(onOutside: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onOutside])
  return ref
}

export function ScopeFilterBar() {
  const years = useScopeStore((s) => s.years)
  const programs = useScopeStore((s) => s.programs)
  const yearOptions = useScopeStore((s) => s.yearOptions)
  const programOptions = useScopeStore((s) => s.programOptions)
  const loadOptions = useScopeStore((s) => s.loadOptions)
  const toggleYear = useScopeStore((s) => s.toggleYear)
  const toggleProgram = useScopeStore((s) => s.toggleProgram)
  const clearScope = useScopeStore((s) => s.clearScope)

  const [open, setOpen] = useState<null | 'years' | 'programs'>(null)
  const ref = useClickOutside(() => setOpen(null))

  useEffect(() => {
    loadOptions()
  }, [loadOptions])

  const hasScope = years.length > 0 || programs.length > 0

  // Group programmes by portfolio era (Initiatives 2022–2024 vs
  // Programs & Accelerators 2025+) — mixing the two eras silently is exactly
  // what references/prms_data_guide.md warns against.
  const eras: string[] = []
  for (const p of programOptions) if (!eras.includes(p.era)) eras.push(p.era)

  return (
    <div
      ref={ref}
      className="relative flex items-center gap-1.5 flex-wrap"
      data-testid="scope-filter-bar"
    >
      <Filter size={13} className="text-text-muted shrink-0" aria-hidden="true" />
      <span className="text-[11px] text-text-muted hidden md:inline">Data scope:</span>
      {/* F15 — what these filters actually do (they constrain the AGENT). */}
      <InfoPopover topic={INFO_TOPICS.filters} />

      {/* Year selector */}
      <button
        type="button"
        onClick={() => setOpen(open === 'years' ? null : 'years')}
        className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all border ${
          years.length
            ? 'bg-accent/15 text-accent border-accent/30'
            : 'border-[var(--border)] text-text-muted hover:bg-surface-2'
        }`}
        data-testid="scope-years-toggle"
      >
        {years.length ? `Years: ${years.join(', ')}` : 'All years'}
        <ChevronDown size={11} />
      </button>

      {/* Programme selector */}
      <button
        type="button"
        onClick={() => setOpen(open === 'programs' ? null : 'programs')}
        className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all border ${
          programs.length
            ? 'bg-accent/15 text-accent border-accent/30'
            : 'border-[var(--border)] text-text-muted hover:bg-surface-2'
        }`}
        data-testid="scope-programs-toggle"
      >
        {programs.length
          ? `${programs.length} programme${programs.length > 1 ? 's' : ''}`
          : 'All programmes'}
        <ChevronDown size={11} />
      </button>

      {hasScope && (
        <button
          type="button"
          onClick={clearScope}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-text-muted hover:text-text-primary hover:bg-surface-2 transition"
          title="Clear the active data scope"
          data-testid="scope-clear"
        >
          <X size={11} /> Clear
        </button>
      )}

      {/* Active scope, always visible so nothing filters silently. */}
      {hasScope && (
        <span
          className="text-[11px] text-text-muted basis-full md:basis-auto"
          role="status"
          data-testid="scope-active-summary"
        >
          Answers constrained to{' '}
          {[
            years.length ? years.join(', ') : null,
            programs.length ? programs.map((p) => p.split(' — ')[0]).join(', ') : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      )}

      {open === 'years' && (
        <div
          className="absolute top-full right-0 mt-1 z-30 w-44 max-h-64 overflow-y-auto rounded-xl glass-strong border border-[var(--border)] shadow-xl p-1"
          data-testid="scope-years-menu"
        >
          {yearOptions.length === 0 && (
            <p className="px-2 py-1.5 text-[11px] text-text-muted">No years available.</p>
          )}
          {yearOptions.map((y) => (
            <label
              key={y}
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-surface-2"
            >
              <input
                type="checkbox"
                checked={years.includes(y)}
                onChange={() => toggleYear(y)}
                data-testid={`scope-year-${y}`}
              />
              {y}
            </label>
          ))}
        </div>
      )}

      {open === 'programs' && (
        <div
          className="absolute top-full right-0 mt-1 z-30 w-72 max-h-72 overflow-y-auto rounded-xl glass-strong border border-[var(--border)] shadow-xl p-1"
          data-testid="scope-programs-menu"
        >
          {programOptions.length === 0 && (
            <p className="px-2 py-1.5 text-[11px] text-text-muted">No programmes available.</p>
          )}
          {eras.map((era) => (
            <div key={era}>
              <p className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wide text-text-muted">
                {era}
              </p>
              {programOptions
                .filter((p) => p.era === era)
                .map((p) => (
                  <label
                    key={p.code}
                    className="flex items-start gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-surface-2"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={programs.includes(p.label)}
                      onChange={() => toggleProgram(p.label)}
                      data-testid={`scope-program-${p.code}`}
                    />
                    <span>{p.label}</span>
                  </label>
                ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
