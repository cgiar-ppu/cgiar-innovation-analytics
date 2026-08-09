/**
 * @file PersonaPicker.tsx
 *
 * Specialist (agent) picker for the chat surface — feedback F3: "can I use a
 * specific agent if I want/need? now I cannot find this option".
 *
 * The nine builtin specialists always existed and the orchestrator routed to
 * them on its own judgement; there was simply no way to ask for one. This pill
 * sits beside the data-scope filters and sends the chosen id with every
 * message, where the backend turns it into a routing instruction
 * (synapsis/persona.py).
 *
 * DEFAULT UNCHANGED: the picker opens on "Auto (recommended)" and stays there
 * until the user chooses. With nothing chosen, no `agent` field is attached and
 * the message frame is byte-identical to the pre-picker one.
 */

import { useEffect, useRef, useState } from 'react'
import { Bot, Check, ChevronDown } from 'lucide-react'
import { usePersonaStore } from '../../stores/persona'

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

export function PersonaPicker() {
  const selected = usePersonaStore((s) => s.selected)
  const options = usePersonaStore((s) => s.options)
  const loadOptions = usePersonaStore((s) => s.loadOptions)
  const selectPersona = usePersonaStore((s) => s.selectPersona)

  const [open, setOpen] = useState(false)
  const ref = useClickOutside(() => setOpen(false))

  useEffect(() => {
    loadOptions()
  }, [loadOptions])

  // Escape closes the menu without changing the selection.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const active = options.find((p) => p.id === selected)
  // The pill always states the CURRENT selection, so a specialist can never be
  // in force invisibly.
  const label = active ? active.name : 'Auto'

  const choose = (id: string | null) => {
    selectPersona(id)
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative flex items-center" data-testid="persona-picker">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          active
            ? `Specialist: ${active.name}. Change the specialist answering your questions`
            : 'Specialist: automatic. Choose a specific specialist'
        }
        title={
          active
            ? `${active.name} — ${active.description}`
            : 'Automatic routing: the orchestrator picks the specialist for each question'
        }
        className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all border ${
          selected
            ? 'bg-accent/15 text-accent border-accent/30'
            : 'border-[var(--border)] text-text-muted hover:bg-surface-2'
        }`}
        data-testid="persona-toggle"
      >
        <Bot size={12} aria-hidden="true" />
        <span className="max-w-[9rem] truncate">{label}</span>
        <ChevronDown size={11} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Choose a specialist"
          className="absolute top-full left-0 mt-1 z-30 w-80 max-h-80 overflow-y-auto rounded-xl glass-strong border border-[var(--border)] shadow-xl p-1"
          data-testid="persona-menu"
        >
          <p className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wide text-text-muted">
            Who should answer?
          </p>

          {/* Automatic routing — the shipped default, always first. */}
          <button
            type="button"
            role="menuitemradio"
            aria-checked={!selected}
            onClick={() => choose(null)}
            className="w-full flex items-start gap-2 px-2 py-2 rounded-lg text-left hover:bg-surface-2"
            data-testid="persona-option-auto"
          >
            <span className="w-4 shrink-0 pt-0.5">
              {!selected && <Check size={13} className="text-accent" aria-hidden="true" />}
            </span>
            <span className="min-w-0">
              <span className="block text-xs font-medium text-text-primary">
                Auto (recommended)
              </span>
              <span className="block text-[11px] text-text-muted leading-snug">
                The orchestrator picks the right specialist for each question.
              </span>
            </span>
          </button>

          <div className="my-1 border-t border-[var(--border)]" />

          {options.length === 0 && (
            <p className="px-2 py-1.5 text-[11px] text-text-muted">
              No specialists available.
            </p>
          )}

          {options.map((p) => (
            <button
              key={p.id}
              type="button"
              role="menuitemradio"
              aria-checked={selected === p.id}
              onClick={() => choose(p.id)}
              className="w-full flex items-start gap-2 px-2 py-2 rounded-lg text-left hover:bg-surface-2"
              data-testid={`persona-option-${p.id}`}
            >
              <span className="w-4 shrink-0 pt-0.5">
                {selected === p.id && (
                  <Check size={13} className="text-accent" aria-hidden="true" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  {p.color && (
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: p.color }}
                      aria-hidden="true"
                    />
                  )}
                  <span className="text-xs font-medium text-text-primary truncate">
                    {p.name}
                  </span>
                </span>
                <span className="block text-[11px] text-text-muted leading-snug mt-0.5 line-clamp-3">
                  {p.description}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Active selection restated in the bar, mirroring the scope summary. */}
      {active && (
        <span
          className="ml-1.5 text-[11px] text-text-muted hidden lg:inline"
          role="status"
          data-testid="persona-active-summary"
        >
          Answered by {active.name}
        </span>
      )}
    </div>
  )
}
