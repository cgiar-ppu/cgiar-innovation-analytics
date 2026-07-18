/**
 * @file DisclaimerFooter.tsx
 *
 * Persistent, always-visible short-form disclaimer banner rendered on every
 * view of the tool (mounted at the layout level). Short form of the CGIAR SO
 * SOP guidance line, per Marc's "maybe in a small footnote, so that it's always
 * there" spec (July 7 call, ~44:33).
 */

import { Info } from 'lucide-react'

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
      </div>
    </footer>
  )
}
