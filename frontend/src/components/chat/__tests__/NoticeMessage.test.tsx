/**
 * Budget / period / cap refusals are visible in the DEFAULT (compact) chat view
 * (verification round, Oct 2026): they used to be folded into "1 system
 * message" and only readable in the expanded view after a click.
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import { MessageList } from '../MessageList'
import { useChatStore } from '../../../stores/chat'
import type { ChatMessage } from '../../../lib/types'

const BUDGET = 'The usage budget for this test period has been used up. Please contact the team.'

beforeEach(() => {
  useChatStore.setState({ messages: [], isBusy: false, currentRunId: null })
})

describe('policy refusal notice', () => {
  it.each(['test_budget', 'test_ended', 'session_limit', 'daily_limit', 'rate_limited'])(
    'an error frame (%s) becomes a visible notice in the compact view', (code) => {
      useChatStore.getState().addUserMessage('How many innovations?')
      useChatStore.getState().handleServerMessage({ type: 'error', code, message: BUDGET })
      const messages = useChatStore.getState().messages
      render(<MessageList messages={messages} />)
      const notice = screen.getByRole('alert')
      expect(notice).toHaveTextContent(BUDGET)
      expect(screen.queryByText(/system message/)).toBeNull()
      expect(useChatStore.getState().isBusy).toBe(false)
    })

  it('is visible in the expanded view too', () => {
    useChatStore.getState().handleServerMessage({ type: 'error', code: 'test_ended', message: 'The test period ended on 2026-11-14.' })
    render(<MessageList messages={useChatStore.getState().messages} expandedView />)
    expect(screen.getByRole('alert')).toHaveTextContent('ended on 2026-11-14')
  })

  it('ordinary system messages still collapse in the compact view', () => {
    const msgs: ChatMessage[] = [
      { id: 'u', role: 'user', content: 'hi', timestamp: 1 },
      { id: 's', role: 'system', content: 'Session started', timestamp: 2, subtype: 'init' },
    ]
    render(<MessageList messages={msgs} />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('system message')).toBeInTheDocument()
  })
})
