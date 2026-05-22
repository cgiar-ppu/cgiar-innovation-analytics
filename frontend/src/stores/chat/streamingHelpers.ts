/**
 * @file streamingHelpers.ts
 * @module stores/chat
 *
 * Helpers for flushing in-progress streaming buffers (text and thinking)
 * into permanent message entries in the chat store.
 *
 * To break the circular dependency (index.ts imports streamingHelpers,
 * streamingHelpers needs to call setState on the store), we use a
 * registration pattern: the store calls {@link registerSetState} after
 * creation, and the helpers use the registered function.
 */

import type { ChatState } from './types'
import { generateId } from '../../lib/utils'

/** Registered setState function, set by the store after creation. */
let _setState: ((updater: (prev: ChatState) => Partial<ChatState>) => void) | null = null

/**
 * Called by the store module after `useChatStore` is created, to provide
 * the setState function without a circular import.
 */
export function registerSetState(fn: (updater: (prev: ChatState) => Partial<ChatState>) => void) {
  _setState = fn
}

function getSetState() {
  if (!_setState) {
    throw new Error('streamingHelpers: setState not registered. Was registerSetState() called?')
  }
  return _setState
}

/**
 * Moves the current {@link ChatState.streamingThinking} buffer into a
 * permanent `thinking` message entry and clears the buffer.
 *
 * Called whenever a non-thinking event arrives mid-stream (e.g. the first
 * `text` chunk signals the thinking phase has ended) or when a run concludes.
 */
export function finalizeThinking(state: ChatState) {
  if (!state.streamingThinking) return
  getSetState()((prev) => {
    // Guard against duplicate: skip if the last thinking message has the
    // same content (can happen during buffer replay / DB history overlap).
    const lastThinking = [...prev.messages].reverse().find(m => m.role === 'thinking')
    if (lastThinking && lastThinking.content === prev.streamingThinking) {
      return { streamingThinking: '' }
    }
    return {
      messages: [
        ...prev.messages,
        {
          id: generateId(),
          role: 'thinking' as const,
          content: prev.streamingThinking,
          timestamp: Date.now(),
          isActive: false,
        },
      ],
      streamingThinking: '',
    }
  })
}

/**
 * Moves the current {@link ChatState.streamingText} buffer into a permanent
 * `assistant` message entry and clears the buffer.
 *
 * Called when a `tool_use`, `result`, or `cancelled` event signals that the
 * current text stream has ended.
 */
export function finalizeText(state: ChatState) {
  if (!state.streamingText) return
  getSetState()((prev) => {
    // Guard against duplicate: if the last assistant message has identical
    // content, skip creating another one.
    const lastAssistant = [...prev.messages].reverse().find(m => m.role === 'assistant')
    if (lastAssistant && lastAssistant.content === prev.streamingText) {
      return { streamingText: '' }
    }
    return {
      messages: [
        ...prev.messages,
        {
          id: generateId(),
          role: 'assistant' as const,
          content: prev.streamingText,
          timestamp: Date.now(),
        },
      ],
      streamingText: '',
    }
  })
}

/**
 * Convenience helper that finalizes both thinking and text buffers in order.
 * Replaces the repeated pattern:
 * ```
 * if (s.streamingThinking) finalizeThinking(s)
 * if (s.streamingText) finalizeText(s)
 * ```
 */
export function finalizeAll(s: ChatState) {
  if (s.streamingThinking) finalizeThinking(s)
  if (s.streamingText) finalizeText(s)
}
