/**
 * @file contacts.ts
 *
 * Wording and built-in defaults for the guardrail "reach out if in doubt"
 * contact route, shared by DisclaimerModal (entry pop-up) and
 * DisclaimerFooter (persistent banner) so the two can never drift apart.
 *
 * Why this exists
 * ---------------
 * Julien Colomer's ask on the Marc↔Jules call (2026-07-07, item 2) was to
 * *point to* the risk framework rather than try to solve it: "scaffolding, not
 * substitute" **and** "reach out if in doubt".
 *
 * Source of truth (2026-09-26, R-09): the contacts are served by
 * `GET /api/config` (`contacts`, env `IA_CONTACT_{SCOPE,TECHNICAL}_{NAME,EMAIL}`)
 * so each environment can change them without a rebuild; see
 * `useGuardrailContacts` in stores/appConfig.ts. The list below is only the
 * fallback shown until the config has loaded. The technical contact moved to
 * the CGIAR mailbox because the synapsis-analytics.com address bounced for an
 * external user (18 Sep 2026).
 *
 * ⚠️ PENDING CONFIRMATION: names and addresses are a DEFAULT chosen by the
 * build, not an approved decision. Jose Luis Berenguer to confirm.
 */

export interface GuardrailContact {
  /** Display name shown in the UI. */
  name: string
  /** Mailto address. */
  email: string
  /** Short parenthetical describing what to ask this person about. */
  remit: string
}

/** Fallback contacts (must match the backend defaults in routes/health.py). */
export const DEFAULT_GUARDRAIL_CONTACTS: GuardrailContact[] = [
  { name: 'Marc Schut', email: 'marc.schut@cgiar.org', remit: 'scope & use' },
  { name: 'Jose Luis Berenguer', email: 'J.Berenguer@cgiar.org', remit: 'technical' },
]

/** @deprecated use `useGuardrailContacts()`; kept for non-React callers. */
export const GUARDRAIL_CONTACTS = DEFAULT_GUARDRAIL_CONTACTS

/** Lead-in sentence, kept in the "scaffolding, not substitute" register. */
export const CONTACT_LEAD_IN = 'In doubt about an output? Reach out before you use it —'

/**
 * Plain-text rendering of the contact line (no markup) — used by the short-form
 * footer and available to any non-React surface that needs the same wording.
 */
export function contactLineText(contacts: GuardrailContact[] = DEFAULT_GUARDRAIL_CONTACTS): string {
  return `${CONTACT_LEAD_IN} ${contacts.map((c) => `${c.name} (${c.remit})`).join(' or ')}.`
}

export const CONTACT_LINE_TEXT = contactLineText()
