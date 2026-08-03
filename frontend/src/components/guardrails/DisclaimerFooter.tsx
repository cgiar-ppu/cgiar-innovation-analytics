/**
 * @file DisclaimerFooter.tsx
 *
 * Persistent, always-visible short-form disclaimer banner rendered on every
 * view of the tool (mounted at the layout level). Short form of the CGIAR SO
 * SOP guidance line, per Marc's "maybe in a small footnote, so that it's always
 * there" spec (July 7 call, ~44:33).
 *
 * Carries the short form of the "reach out if in doubt" contact route
 * (Jules-call item 2, 2026-07-07) — one mailto per contact, shared with
 * DisclaimerModal via ./contacts.ts.
 */

import { Info } from 'lucide-react'
import { GUARDRAIL_CONTACTS } from './contacts'

export default function DisclaimerFooter() {
  return (
    <footer
      className="shrink-0 z-20 border-t border-[var(--border)] bg-[var(--bg)]/80 backdrop-blur px-4 py-1.5"
      role="contentinfo"
      aria-label="AI-content disclaimer"
    >
      <div className="flex items-center justify-center gap-2 text-[11px] leading-tight text-[var(--text-muted)] text-center">
        <Info className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        <span>
          AI outputs are for guidance only and require human quality assurance
          before use or citation. Based on CGIAR innovation data (PRMS) with
          AI-added interpretation.
        </span>
        <span data-testid="disclaimer-footer-contact">
          In doubt?{' '}
          {GUARDRAIL_CONTACTS.map((c, i) => (
            <span key={c.email}>
              {i > 0 && ' or '}
              <a
                href={`mailto:${c.email}`}
                className="underline underline-offset-2 hover:text-[var(--accent)]"
              >
                {c.name}
              </a>{' '}
              ({c.remit})
            </span>
          ))}
          .
        </span>
      </div>
    </footer>
  )
}
