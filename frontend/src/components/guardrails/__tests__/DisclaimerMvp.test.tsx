/**
 * MVP test labelling in the "Before you begin" pop-up (Oct 2026).
 *
 * Four short statements are added — prototype for testing, AI with a human in
 * the loop, factual PRMS data with anything beyond it labelled, the one-month
 * test period and what happens after — while the original disclaimer text and
 * the "I understand" click stay as they were.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import DisclaimerModal, { MVP_TEST_STATEMENTS } from '../DisclaimerModal'
import DisclaimerFooter from '../DisclaimerFooter'
import { useAppConfigStore } from '../../../stores/appConfig'

describe('MVP test statements in the disclaimer', () => {
  beforeEach(() => useAppConfigStore.getState().reset())

  it('lists exactly four short statements', () => {
    expect(MVP_TEST_STATEMENTS).toHaveLength(4)
    render(<DisclaimerModal />)
    const list = screen.getByTestId('disclaimer-mvp-statements')
    expect(within(list).getAllByRole('listitem')).toHaveLength(4)
  })

  it('says prototype for testing, AI with a human in the loop, factual data labelled, one-month test', () => {
    render(<DisclaimerModal />)
    const text = screen.getByTestId('disclaimer-mvp-statements').textContent ?? ''
    expect(text).toMatch(/MVP/)
    expect(text).toMatch(/not a final product/i)
    expect(text).toMatch(/uses AI/i)
    expect(text).toMatch(/human in the loop/i)
    expect(text).toMatch(/check every output/i)
    expect(text).toMatch(/factual data from the CGIAR results database \(PRMS\)/i)
    expect(text).toMatch(/clearly label anything that goes beyond it/i)
    expect(text).toMatch(/one month/i)
    expect(text).toMatch(/after that, test access ends/i)
  })

  it('keeps the original disclaimer text and the "I understand" action', () => {
    render(<DisclaimerModal />)
    expect(screen.getByText(/This tool draws from the CGIAR innovation database \(PRMS\)/)).toBeInTheDocument()
    expect(screen.getByText('AI outputs are for guidance only.')).toBeInTheDocument()
    expect(screen.getByText(/Scaffolding, not substitute/)).toBeInTheDocument()
    expect(screen.getByTestId('disclaimer-understand')).toHaveTextContent('I understand')
    expect(screen.getByText(/MVP test release/)).toBeInTheDocument()
  })

  it('the footer carries the MVP test label next to the guidance line', () => {
    render(<DisclaimerFooter />)
    expect(screen.getByTestId('disclaimer-footer-mvp')).toHaveTextContent('MVP test version.')
    expect(screen.getByRole('contentinfo')).toHaveTextContent(/AI outputs are for guidance only/)
  })
})
