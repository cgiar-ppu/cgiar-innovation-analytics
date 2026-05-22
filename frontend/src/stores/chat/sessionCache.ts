/**
 * @file sessionCache.ts
 * @module stores/chat
 *
 * Session cache operations for preserving streaming state across session
 * switches. The cache is a plain Map<string, CachedSessionState> stored
 * inside the Zustand state as `_sessionCache`.
 *
 * These factory functions receive `get` and `set` from the Zustand creator
 * and return the action implementations.
 */

import type { StoreApi } from 'zustand'
import type { ChatState, CachedSessionState } from './types'

type Get = StoreApi<ChatState>['getState']
type Set = StoreApi<ChatState>['setState']

/** Creates all session-cache action implementations. */
export function createSessionCacheActions(set: Set, get: Get) {
  return {
    cacheCurrentSession: (sessionId: string) => {
      const s = get()
      get()._sessionCache.set(sessionId, {
        messages: s.messages,
        streamingText: s.streamingText,
        streamingThinking: s.streamingThinking,
        isBusy: s.isBusy,
        replayMode: s.replayMode,
        activeAgent: s.activeAgent,
        toolActivity: s.toolActivity,
        pendingAttachments: s.pendingAttachments,
        currentRunId: s.currentRunId,
      })
    },

    restoreSession: (sessionId: string): boolean => {
      const cached = get()._sessionCache.get(sessionId)
      if (!cached) return false
      set({
        messages: cached.messages,
        streamingText: cached.streamingText,
        streamingThinking: cached.streamingThinking,
        isBusy: cached.isBusy,
        replayMode: cached.replayMode,
        activeAgent: cached.activeAgent,
        toolActivity: cached.toolActivity,
        pendingAttachments: cached.pendingAttachments,
        currentRunId: cached.currentRunId,
      })
      // Remove from cache -- it's now the active state
      get()._sessionCache.delete(sessionId)
      return true
    },

    updateCachedSession: (sessionId: string, updates: Partial<CachedSessionState>) => {
      const cached = get()._sessionCache.get(sessionId)
      if (cached) {
        get()._sessionCache.set(sessionId, { ...cached, ...updates })
      }
    },

    appendToCachedStream: (sessionId: string, field: 'streamingText' | 'streamingThinking', content: string) => {
      const cached = get()._sessionCache.get(sessionId)
      if (cached) {
        cached[field] += content
      }
    },

    invalidateCachedSession: (sessionId: string) => {
      get()._sessionCache.delete(sessionId)
    },
  }
}
