/**
 * @file messageHandlers.ts
 * @module stores/chat
 *
 * The `handleServerMessage` implementation, extracted from the main store
 * definition for readability. Routes each {@link ServerMessage} variant to
 * the appropriate state mutation.
 */

import type { StoreApi } from 'zustand'
import type { ServerMessage } from '../../lib/types'
import type { ChatState } from './types'
import { generateId } from '../../lib/utils'
import { finalizeThinking, finalizeAll } from './streamingHelpers'
import { isSuppressedSystemMessage } from './systemMessageFilter'

type Get = StoreApi<ChatState>['getState']
type Set = StoreApi<ChatState>['setState']

// RAF buffering for text deltas — batches rapid updates to ~16/s
let _pendingText = ''
let _pendingThinking = ''
let _rafId: number | null = null

let _storeSet: Set | null = null
let _storeGet: Get | null = null

/** Flush any pending RAF-buffered text/thinking deltas immediately.
 *  Exported for use in tests where RAF doesn't fire naturally. */
export function flushStreamingDeltas() {
  if (_rafId !== null) {
    cancelAnimationFrame(_rafId)
  }
  _flushPendingDeltas()
}

function _flushPendingDeltas() {
  _rafId = null
  if (!_storeSet || !_storeGet) return
  const st = _storeGet()
  const updates: Partial<ChatState> = {}
  if (_pendingText) {
    updates.streamingText = st.streamingText + _pendingText
    _pendingText = ''
  }
  if (_pendingThinking) {
    updates.streamingThinking = st.streamingThinking + _pendingThinking
    _pendingThinking = ''
  }
  if (Object.keys(updates).length > 0) {
    _storeSet(updates)
  }
}

/**
 * Creates the `handleServerMessage` action.
 * Receives `set`/`get` from the Zustand creator so it can read and mutate state.
 */
export function createHandleServerMessage(set: Set, get: Get) {
  _storeSet = set
  _storeGet = get

  return (msg: ServerMessage) => {
    // During buffer replay, only process streaming deltas (text/thinking).
    // Structural events (tool_use, tool_result, result) are already loaded
    // from the database via loadHistory called during buffer_replay_start.
    const replayMode = get().replayMode
    if (replayMode && msg.type !== 'text' && msg.type !== 'thinking' && msg.type !== 'session_complete') {
      return
    }

    // --- Turn-level run_id scoping (Fix 1) ---
    const msgRunId = (msg as { run_id?: string }).run_id
    const state = get()

    // Accept run_id from the first non-completion event of a new turn.
    // Completion events (session_complete, result) should not bootstrap
    // the run_id — they could be stale broadcasts from previous turns.
    if (msgRunId && !state.currentRunId
        && msg.type !== 'session_complete' && msg.type !== 'result') {
      set({ currentRunId: msgRunId })
    }

    // Reject stale events: only when currentRunId IS set and doesn't match
    if (msgRunId && state.currentRunId && msgRunId !== state.currentRunId) {
      console.warn('[Chat] Ignoring stale message from run', msgRunId, 'current:', state.currentRunId)
      return
    }

    switch (msg.type) {
      case 'text': {
        _pendingText += msg.content
        const st = get()
        if (st.streamingThinking || _pendingThinking) {
          if (_rafId !== null) {
            cancelAnimationFrame(_rafId)
          }
          _flushPendingDeltas()
          finalizeThinking(get())
        }
        if (_rafId === null) {
          _rafId = requestAnimationFrame(_flushPendingDeltas)
        }
        break
      }

      case 'thinking': {
        _pendingThinking += msg.content
        if (_rafId === null) {
          _rafId = requestAnimationFrame(_flushPendingDeltas)
        }
        break
      }

      case 'tool_use': {
        if (_rafId !== null) {
          cancelAnimationFrame(_rafId)
        }
        _flushPendingDeltas()
        finalizeAll(get())

        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'tool_use',
              content: '',
              timestamp: Date.now(),
              tool: msg.tool,
              toolInput: msg.input,
              toolUseId: msg.tool_use_id,
            },
          ],
          // Transition from "preparing" -> "running" (tool dispatched, awaiting result)
          toolActivity: { tool: msg.tool, phase: 'running' },
        }))
        break
      }

      case 'tool_result': {
        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'tool_result',
              content: msg.content,
              timestamp: Date.now(),
              toolUseId: msg.tool_use_id,
              isError: msg.is_error,
            },
          ],
          toolActivity: null,
        }))
        break
      }

      case 'result': {
        if (_rafId !== null) {
          cancelAnimationFrame(_rafId)
        }
        _flushPendingDeltas()
        const s = get()
        finalizeAll(s)

        // Extract result_text for slash commands that return output without streaming
        const resultMsg = msg as { type: 'result'; error_detail?: string; result_text?: string; estimated_cost: number | null; turns: number; duration_ms: number; auth_method: string; is_error: boolean }
        const resultText = resultMsg.result_text || ''

        // Detect slash commands that produced no visible output.
        const currentMessages = get().messages
        const lastUserMsg = [...currentMessages].reverse().find(m => m.role === 'user')
        const isSlashCommand = lastUserMsg?.content?.startsWith('/')
        const hadStreamedContent = s.streamingText !== '' // non-empty BEFORE finalization
        const hadStreamedThinking = s.streamingThinking !== ''

        // Count messages added since the last user message (tool_use, assistant, etc.)
        let contentMessagesSinceLast = 0
        if (lastUserMsg) {
          for (let i = currentMessages.length - 1; i >= 0; i--) {
            if (currentMessages[i] === lastUserMsg) break
            const role = currentMessages[i]?.role
            if (role === 'assistant' || role === 'tool_use') contentMessagesSinceLast++
          }
        }

        // If a slash command returned text in result_text, show it
        if (resultText && !hadStreamedContent) {
          set((prev) => ({
            messages: [
              ...prev.messages,
              {
                id: generateId(),
                role: 'assistant',
                content: resultText,
                timestamp: Date.now(),
              },
            ],
          }))
        }
        // If a slash command produced NO output at all, show feedback
        else if (isSlashCommand && !hadStreamedContent && !hadStreamedThinking && contentMessagesSinceLast === 0 && !resultText) {
          const cmd = lastUserMsg?.content?.split(/\s/)[0] ?? ''
          set((prev) => ({
            messages: [
              ...prev.messages,
              {
                id: generateId(),
                role: 'system',
                content: `Command \`${cmd}\` executed. This command may not produce visible output through the web interface — try it in the Claude Code CLI for full output.`,
                timestamp: Date.now(),
              },
            ],
          }))
        }

        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'result',
              content: resultMsg.error_detail || '',
              timestamp: Date.now(),
              estimatedCost: resultMsg.estimated_cost,
              turns: resultMsg.turns,
              durationMs: resultMsg.duration_ms,
              authMethod: resultMsg.auth_method,
              isError: resultMsg.is_error,
              resultText,
            },
          ],
          isBusy: false,
          cancelled: false,
          toolActivity: null,
        }))
        break
      }

      case 'cancelled': {
        if (_rafId !== null) {
          cancelAnimationFrame(_rafId)
        }
        _flushPendingDeltas()
        finalizeAll(get())
        set({ isBusy: false, cancelled: false })
        break
      }

      case 'session': {
        // Session ID is managed in the sessions store / hook
        break
      }

      case 'system': {
        const data = msg.data
        const content = typeof data === 'string' ? data : JSON.stringify(data)
        if (!content || content === '{}' || content === 'null') break
        // Drop SDK per-turn token/usage telemetry ("thinking_tokens" pills);
        // the thinking content block (role: 'thinking') is unaffected.
        if (isSuppressedSystemMessage(msg.subtype, content)) break
        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'system',
              content,
              timestamp: Date.now(),
              subtype: msg.subtype,
            },
          ],
        }))
        break
      }

      case 'error': {
        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'system',
              content: msg.message,
              timestamp: Date.now(),
            },
          ],
          isBusy: false,
          cancelled: false,
        }))
        break
      }

      case 'aup_error': {
        const aupMsg = msg as { type: 'aup_error'; message: string; fallback_model: string }
        const lastUserMsg = get().messages.filter(m => m.role === 'user').pop()?.content || ''
        set({
          aupError: {
            hasError: true,
            message: aupMsg.message,
            fallbackModel: aupMsg.fallback_model,
            lastUserMessage: lastUserMsg,
          },
          isBusy: false,
        })
        set((prev) => ({
          messages: [
            ...prev.messages,
            {
              id: generateId(),
              role: 'system',
              content: `\u26A0\uFE0F This request was flagged by the model's usage policy. You can retry with ${aupMsg.fallback_model}.`,
              timestamp: Date.now(),
              subtype: 'aup_error',
            },
          ],
        }))
        break
      }

      case 'agent_activity': {
        const actMsg = msg as { type: 'agent_activity'; agent: string; status: 'started' | 'completed'; tool_use_id: string }
        set({
          activeAgent: {
            name: actMsg.agent,
            status: actMsg.status,
            toolUseId: actMsg.tool_use_id,
          },
        })
        break
      }

      case 'tool_generating': {
        if (_rafId !== null) {
          cancelAnimationFrame(_rafId)
        }
        _flushPendingDeltas()
        finalizeAll(get())

        const tgMsg = msg as { type: 'tool_generating'; tool: string; tool_use_id: string }
        set({ toolActivity: { tool: tgMsg.tool, phase: 'preparing' } })
        break
      }

      case 'session_complete': {
        if (_rafId !== null) {
          cancelAnimationFrame(_rafId)
        }
        _flushPendingDeltas()
        finalizeAll(get())
        set({ isBusy: false, cancelled: false, activeAgent: null })
        break
      }
    }
  }
}
