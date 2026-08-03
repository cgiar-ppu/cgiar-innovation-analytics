/**
 * @file DisclaimerModal.tsx
 *
 * Entry pop-up modal shown on app load (per authenticated identity) before the
 * user can reach the chat / analytics UI. Wording per Marc Schut's July 7 spec
 * (draws from the innovation database + adds AI reflections/interpretation from
 * other available information + human quality assurance always required) plus
 * the CGIAR SO SOP guidance line. The user must click "I understand" to proceed.
 *
 * Also carries the "reach out if in doubt" contact route (Jules-call item 2,
 * 2026-07-07) — see ./contacts.ts for the wording and the pending-confirmation
 * caveat on who the named contacts are.
 *
 * Follows the repo's house modal style (framer-motion + glass Tailwind), the
 * same pattern used by AgentDetailModal.
 */

import { motion } from 'framer-motion'
import { ShieldCheck } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'
import { GUARDRAIL_CONTACTS, CONTACT_LEAD_IN } from './contacts'

export default function DisclaimerModal() {
  const acknowledge = useAuthStore((s) => s.acknowledgeDisclaimer)

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="disclaimer-title"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-xl overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center gap-3 p-5 border-b border-[var(--border)]">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center bg-[var(--accent)]/10">
            <ShieldCheck className="w-6 h-6 text-[var(--accent)]" />
          </div>
          <div>
            <h2 id="disclaimer-title" className="text-lg font-semibold text-[var(--text)]">
              Before you begin
            </h2>
            <p className="text-xs text-[var(--text-muted)]">
              CGIAR Innovation Analytics — AI-assisted tool
            </p>
          </div>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 text-sm leading-relaxed text-[var(--text)]">
          <p>
            This tool draws from the CGIAR innovation database (PRMS), and it also
            adds reflections and interpretation based on other available information.
            A human quality-assurance step should always take place before any output
            is used, shared, or cited.
          </p>

          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-subtle,rgba(0,0,0,0.03))] p-3 text-[var(--text-muted)]">
            <strong className="text-[var(--text)]">AI outputs are for guidance only.</strong>{' '}
            Final decisions require human-led analysis.
          </div>

          <p className="text-xs text-[var(--text-muted)]">
            Scaffolding, not substitute: AI-generated content has no institutional
            standing until it is reviewed, validated, and approved by a responsible
            human author.
          </p>

          {/* "Reach out if in doubt" — the contact half of Jules-call item 2. */}
          <p className="text-xs text-[var(--text-muted)]" data-testid="disclaimer-contact">
            {CONTACT_LEAD_IN}{' '}
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
          </p>
        </div>

        {/* Footer / action */}
        <div className="flex justify-end gap-2 p-5 border-t border-[var(--border)]">
          <button
            type="button"
            onClick={acknowledge}
            className="px-5 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 transition"
            data-testid="disclaimer-understand"
          >
            I understand
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
