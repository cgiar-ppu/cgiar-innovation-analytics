/**
 * @file InfoPopover.tsx
 *
 * A small ⓘ button that opens a short explainer for one feature area
 * (feedback F15: "tour/information button per functionality").
 *
 * Deliberately a POPOVER, not a guided tour: the instruction was to prefer
 * simple popovers over a heavy tour library. One shared component + per-surface
 * copy in `infoCopy.ts` means the explainers cannot drift apart in style, and
 * adding one to a new surface is a two-line change.
 *
 * Accessibility:
 * - the trigger is a real <button> with an aria-label naming the area;
 * - `aria-expanded` / `aria-haspopup="dialog"` reflect the state;
 * - Escape closes it and returns focus to the trigger;
 * - the panel is `role="dialog"` with `aria-label`, focused on open;
 * - a click outside closes it.
 *
 * It is NOT a modal (no focus trap, no aria-modal): it is a passive explainer
 * that must never block the surface it explains.
 */

import { useEffect, useRef, useState } from 'react'
import { Info, X } from 'lucide-react'
import type { InfoTopic } from './infoCopy'

type Align = 'left' | 'right'
type Size = 'sm' | 'md'

interface Props {
  /** The explainer to show. */
  topic: InfoTopic
  /** Which edge the panel is anchored to. Default: left. */
  align?: Align
  /** Icon size. `sm` suits dense filter bars, `md` a page header. */
  size?: Size
  /** Extra classes for the trigger button. */
  className?: string
}

export function InfoPopover({ topic, align = 'left', size = 'sm', className = '' }: Props) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  // Click outside closes.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Escape closes and hands focus back to the trigger.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const iconPx = size === 'md' ? 16 : 13

  return (
    <span ref={wrapRef} className="relative inline-flex items-center">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`About ${topic.title}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={`About ${topic.title}`}
        data-testid={`info-button-${topic.id}`}
        className={`inline-flex items-center justify-center rounded-full text-text-muted hover:text-text-primary hover:bg-surface-2 transition-colors p-1 ${className}`}
      >
        <Info size={iconPx} aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={topic.title}
          tabIndex={-1}
          data-testid={`info-panel-${topic.id}`}
          className={`absolute top-full mt-2 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-2xl glass-strong border border-[var(--border)] shadow-xl p-4 text-left ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <h3 className="text-xs font-semibold text-text-primary">{topic.title}</h3>
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                buttonRef.current?.focus()
              }}
              aria-label={`Close the ${topic.title} explainer`}
              className="shrink-0 rounded-lg p-0.5 text-text-muted hover:text-text-primary hover:bg-surface-2 transition-colors"
            >
              <X size={12} aria-hidden="true" />
            </button>
          </div>

          {topic.body.map((para, i) => (
            <p key={i} className="text-[11px] leading-relaxed text-text-muted mb-1.5 last:mb-0">
              {para}
            </p>
          ))}
        </div>
      )}
    </span>
  )
}
