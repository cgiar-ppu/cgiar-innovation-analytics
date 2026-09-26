/**
 * Tests for the "reach out if in doubt" contact route (2026-08-03).
 *
 * Closes the second half of Jules-call item 2 (2026-07-07): the disclaimer
 * surfaces told users output needs validation but gave them nobody to ask.
 *
 * Covers:
 * - the modal renders the contact line with a mailto per contact, and still
 *   renders the "I understand" action (data-testid contract unchanged);
 * - the persistent footer renders the same contacts from the shared module;
 * - both surfaces read from contacts.ts, so they cannot drift apart.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import DisclaimerModal from '../DisclaimerModal'
import DisclaimerFooter from '../DisclaimerFooter'
import { GUARDRAIL_CONTACTS, CONTACT_LINE_TEXT } from '../contacts'
import { useAppConfigStore } from '../../../stores/appConfig'
import type { AppConfig } from '../../../lib/types'

describe('guardrail contact route', () => {
  beforeEach(() => useAppConfigStore.getState().reset())

  it('the shared contacts module defines at least one reachable contact', () => {
    expect(GUARDRAIL_CONTACTS.length).toBeGreaterThan(0)
    for (const c of GUARDRAIL_CONTACTS) {
      expect(c.email).toMatch(/^[^@\s]+@[^@\s]+\.[^@\s]+$/)
      expect(c.name.length).toBeGreaterThan(0)
      expect(c.remit.length).toBeGreaterThan(0)
    }
    expect(CONTACT_LINE_TEXT).toMatch(/in doubt/i)
  })

  it('DisclaimerModal shows the contact line with a mailto per contact', () => {
    render(<DisclaimerModal />)

    const line = screen.getByTestId('disclaimer-contact')
    expect(line).toHaveTextContent(/in doubt about an output\?/i)

    for (const c of GUARDRAIL_CONTACTS) {
      const link = within(line).getByRole('link', { name: c.name })
      expect(link).toHaveAttribute('href', `mailto:${c.email}`)
      expect(line).toHaveTextContent(c.remit)
    }
  })

  it('DisclaimerModal still exposes the "I understand" action', () => {
    render(<DisclaimerModal />)
    expect(screen.getByTestId('disclaimer-understand')).toBeInTheDocument()
  })

  it('DisclaimerFooter shows the same contacts', () => {
    render(<DisclaimerFooter />)

    const line = screen.getByTestId('disclaimer-footer-contact')
    expect(line).toHaveTextContent(/in doubt\?/i)
    for (const c of GUARDRAIL_CONTACTS) {
      expect(within(line).getByRole('link', { name: c.name })).toHaveAttribute(
        'href',
        `mailto:${c.email}`,
      )
    }
  })
})

describe('configurable contact (R-09, 2026-09-26)', () => {
  beforeEach(() => useAppConfigStore.getState().reset())

  it('the built-in technical default is the CGIAR mailbox, never the bounced address', () => {
    const technical = GUARDRAIL_CONTACTS.find((c) => c.remit === 'technical')
    expect(technical?.email).toBe('J.Berenguer@cgiar.org')
    expect(JSON.stringify(GUARDRAIL_CONTACTS)).not.toContain('synapsis-analytics.com')
    // Marc stays the scope & use contact.
    expect(GUARDRAIL_CONTACTS.find((c) => c.remit === 'scope & use')?.email).toBe('marc.schut@cgiar.org')
  })

  it('modal and footer follow the contacts served by /api/config', () => {
    useAppConfigStore.setState({
      config: { model: 'm', contacts: [{ name: 'IA support desk', email: 'ia-support@cgiar.org', remit: 'technical' }] } as unknown as AppConfig,
      loadedFor: 'anonymous',
    })
    render(<><DisclaimerModal /><DisclaimerFooter /></>)
    for (const id of ['disclaimer-contact', 'disclaimer-footer-contact']) {
      const line = screen.getByTestId(id)
      expect(within(line).getByRole('link', { name: 'IA support desk' })).toHaveAttribute('href', 'mailto:ia-support@cgiar.org')
      expect(within(line).queryByRole('link', { name: 'Marc Schut' })).toBeNull()
    }
  })
})
