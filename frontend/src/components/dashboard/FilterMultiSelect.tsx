/**
 * @file FilterMultiSelect.tsx
 *
 * Compact "All … / multiselect" dropdown for the Innovation Analytics
 * dashboard's CGIAR Centre and Program/Accelerator filters (Marc Schut,
 * 2026-10-08). Same look and behaviour as YearMultiSelect (which stays as-is):
 * a pill that always states the active selection, a checkbox menu, and an
 * explicit "All …" escape hatch. Options may be grouped (the programs list is
 * grouped by portfolio era, like the chat ScopeFilterBar).
 *
 * An empty selection means "no filter" (all centres / all programs).
 */

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'

export interface FilterOption {
  /** Value sent to the API (e.g. "CENTER-05", "SP01"). */
  value: string
  /** Short text for the pill (e.g. "CIMMYT", "SP01"). */
  short: string
  /** Full text in the menu (e.g. "CIMMYT — International Maize and …"). */
  label: string
  /** Optional group heading (e.g. the portfolio era). */
  group?: string
}

interface FilterMultiSelectProps {
  /** Pill prefix, e.g. "Centres". */
  name: string
  /** Escape-hatch text, e.g. "All centres". */
  allLabel: string
  /** Plural noun for "3 centres". */
  plural: string
  options: FilterOption[]
  /** Selected values; empty array means no filter. */
  value: string[]
  onChange: (values: string[]) => void
  disabled?: boolean
  /** data-testid prefix, e.g. "dashboard-centre". */
  testId: string
  /** Menu width class. */
  menuWidth?: string
}

/** Pill text: "All centres" / "CIMMYT" / "CIMMYT + IITA" / "3 centres". */
export function selectionLabel(
  value: string[],
  options: FilterOption[],
  allLabel: string,
  plural: string
): string {
  if (value.length === 0) return allLabel
  const short = (v: string) => options.find((o) => o.value === v)?.short ?? v
  if (value.length === 1) return short(value[0]!)
  if (value.length === 2) return `${short(value[0]!)} + ${short(value[1]!)}`
  return `${value.length} ${plural}`
}

export default function FilterMultiSelect({
  name,
  allLabel,
  plural,
  options,
  value,
  onChange,
  disabled,
  testId,
  menuWidth = 'w-80',
}: FilterMultiSelectProps) {
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

  const toggle = (v: string) => {
    // Keep the menu's order so the pill text is stable.
    const order = options.map((o) => o.value)
    const next = value.includes(v) ? value.filter((x) => x !== v) : [...value, v]
    onChange(next.sort((a, b) => order.indexOf(a) - order.indexOf(b)))
  }

  const groups: string[] = []
  for (const o of options) {
    const g = o.group ?? ''
    if (!groups.includes(g)) groups.push(g)
  }

  return (
    <div ref={ref} className="relative" data-testid={`${testId}-filter`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled || options.length === 0}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={value.length > 2 ? value.map((v) => options.find((o) => o.value === v)?.short ?? v).join(', ') : undefined}
        className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border bg-[var(--surface-solid)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[#427730]/40 ${
          value.length ? 'border-[#427730]/60' : 'border-[var(--border)]'
        }`}
        data-testid={`${testId}-toggle`}
      >
        <span className="hidden sm:inline text-[var(--text-muted)]">{name}</span>
        <span className="font-medium max-w-[11rem] truncate">{selectionLabel(value, options, allLabel, plural)}</span>
        <ChevronDown className="w-3.5 h-3.5 text-[var(--text-muted)]" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-multiselectable="true"
          className={`absolute top-full right-0 mt-1 z-30 ${menuWidth} max-h-96 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface-solid)] shadow-xl p-1`}
          data-testid={`${testId}-menu`}
        >
          <button
            type="button"
            onClick={() => onChange([])}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left hover:bg-[var(--surface-2)] text-[var(--text)]"
            data-testid={`${testId}-all`}
          >
            <span className="w-3.5 shrink-0">
              {value.length === 0 && <Check className="w-3.5 h-3.5 text-[#427730]" />}
            </span>
            {allLabel}
          </button>
          <div className="my-1 border-t border-[var(--border)]" />
          {groups.map((g) => (
            <div key={g || 'all'}>
              {g && (
                <div
                  className="px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]"
                  data-testid={`${testId}-group`}
                >
                  {g}
                </div>
              )}
              {options
                .filter((o) => (o.group ?? '') === g)
                .map((o) => (
                  <label
                    key={o.value}
                    className="flex items-start gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-[var(--surface-2)] text-[var(--text)]"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={value.includes(o.value)}
                      onChange={() => toggle(o.value)}
                      data-testid={`${testId}-option-${o.value}`}
                    />
                    <span>{o.label}</span>
                  </label>
                ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
