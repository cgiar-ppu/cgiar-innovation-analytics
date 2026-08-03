/**
 * @file contacts.ts
 *
 * Single source of truth for the guardrail "reach out if in doubt" contact
 * route, shared by DisclaimerModal (entry pop-up) and DisclaimerFooter
 * (persistent banner) so the two can never drift apart.
 *
 * Why this exists
 * ---------------
 * Julien Colomer's ask on the Marc↔Jules call (2026-07-07, item 2) was to
 * *point to* the risk framework rather than try to solve it: "scaffolding, not
 * substitute" **and** "reach out if in doubt". Only the first half shipped in
 * the July-7 guardrails sprint — the disclaimer told users AI output needs
 * human validation but gave them nobody to ask. This closes that half.
 *
 * ⚠️ PENDING CONFIRMATION (decision D2, 2026-08-03 gap audit): the names and
 * the split below are a sensible DEFAULT chosen by the build, not an approved
 * decision. Jose Luis Berenguer to confirm (or replace with a shared inbox /
 * a single owner) before this reaches anyone outside the dev testers. The
 * addresses are the ones already carried in `config/allowed_users.json`.
 */

export interface GuardrailContact {
  /** Display name shown in the UI. */
  name: string
  /** Mailto address. */
  email: string
  /** Short parenthetical describing what to ask this person about. */
  remit: string
}

/** The people a user should reach out to when in doubt about an output. */
export const GUARDRAIL_CONTACTS: GuardrailContact[] = [
  { name: 'Marc Schut', email: 'marc.schut@cgiar.org', remit: 'scope & use' },
  {
    name: 'Jose Luis Berenguer',
    email: 'jose@synapsis-analytics.com',
    remit: 'technical',
  },
]

/** Lead-in sentence, kept in the "scaffolding, not substitute" register. */
export const CONTACT_LEAD_IN = 'In doubt about an output? Reach out before you use it —'

/**
 * Plain-text rendering of the contact line (no markup) — used by the short-form
 * footer and available to any non-React surface that needs the same wording.
 */
export const CONTACT_LINE_TEXT = `${CONTACT_LEAD_IN} ${GUARDRAIL_CONTACTS.map(
  (c) => `${c.name} (${c.remit})`,
).join(' or ')}.`
