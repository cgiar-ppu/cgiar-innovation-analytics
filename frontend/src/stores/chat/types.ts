/**
 * @file types.ts
 * @module stores/chat
 *
 * Type definitions for the chat Zustand store.
 * Re-exports {@link ChatMessage} and {@link PendingAttachment} from lib/types
 * for convenience; defines store-internal types here.
 */

import type { ChatMessage, ServerMessage, PendingAttachment } from '../../lib/types'

/** Snapshot of session-specific chat state preserved across session switches. */
export interface CachedSessionState {
  messages: ChatMessage[]
  streamingText: string
  streamingThinking: string
  isBusy: boolean
  replayMode: boolean
  activeAgent: { name: string; status: 'started' | 'completed'; toolUseId: string } | null
  toolActivity: { tool: string; phase: 'preparing' | 'running' } | null
  pendingAttachments: PendingAttachment[]
  currentRunId: string | null
}

/**
 * Shape of the chat Zustand store.
 * Combines reactive state fields with action methods.
 */
export interface ChatState {
  messages: ChatMessage[]
  streamingText: string
  streamingThinking: string
  isBusy: boolean
  cancelled: boolean
  currentRunId: string | null
  activeAgent: { name: string; status: 'started' | 'completed'; toolUseId: string } | null
  toolActivity: { tool: string; phase: 'preparing' | 'running' } | null
  aupError: { hasError: boolean; message: string; fallbackModel: string; lastUserMessage: string } | null
  pendingAttachments: PendingAttachment[]
  replayMode: boolean

  setReplayMode: (mode: boolean) => void
  handleServerMessage: (msg: ServerMessage) => void
  addUserMessage: (text: string) => void
  setBusy: (busy: boolean) => void
  setCancelled: (cancelled: boolean) => void
  addAttachment: (attachment: PendingAttachment) => void
  removeAttachment: (filePath: string) => void
  clearAttachments: () => void
  clearMessages: () => void
  loadHistory: (sessionId: string, signal?: AbortSignal, preserveBusy?: boolean) => Promise<void>

  _sessionCache: Map<string, CachedSessionState>
  cacheCurrentSession: (sessionId: string) => void
  restoreSession: (sessionId: string) => boolean
  updateCachedSession: (sessionId: string, updates: Partial<CachedSessionState>) => void
  appendToCachedStream: (sessionId: string, field: 'streamingText' | 'streamingThinking', content: string) => void
  invalidateCachedSession: (sessionId: string) => void
}
