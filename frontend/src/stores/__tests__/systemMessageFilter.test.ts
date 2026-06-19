/**
 * Tests for isSuppressedSystemMessage — the predicate that hides SDK per-turn
 * token/usage telemetry pills from the chat while keeping legitimate system
 * messages visible.
 */
import { describe, it, expect } from 'vitest'
import { isSuppressedSystemMessage } from '../chat/systemMessageFilter'

describe('isSuppressedSystemMessage', () => {
  it('suppresses the SDK per-turn telemetry subtypes (the token pills)', () => {
    expect(isSuppressedSystemMessage('task_started', '{}')).toBe(true)
    expect(isSuppressedSystemMessage('task_progress', '{"usage":{"total_tokens":1234}}')).toBe(true)
    expect(isSuppressedSystemMessage('task_notification', '{"status":"completed"}')).toBe(true)
  })

  it('keeps legitimate system messages visible', () => {
    expect(isSuppressedSystemMessage('init', '{"model":"opus"}')).toBe(false)
    expect(isSuppressedSystemMessage('aup_error', 'flagged')).toBe(false)
    expect(isSuppressedSystemMessage('workflow_context', 'ctx')).toBe(false)
    expect(isSuppressedSystemMessage('mirror_error', 'append failed')).toBe(false)
    expect(isSuppressedSystemMessage('file_upload', 'uploaded report.xlsx')).toBe(false)
  })

  it('keeps system messages with no subtype (local UX notices, errors)', () => {
    expect(isSuppressedSystemMessage(undefined, 'Command `/usage` executed.')).toBe(false)
    expect(isSuppressedSystemMessage(undefined, 'Some error occurred')).toBe(false)
  })

  it('does not over-match unknown subtypes that merely mention tokens', () => {
    // A future/unknown subtype is not suppressed unless explicitly allowlisted,
    // so we never hide a genuine message by accident.
    expect(isSuppressedSystemMessage('some_future_notice', 'thinking_tokens: 42')).toBe(false)
  })
})
