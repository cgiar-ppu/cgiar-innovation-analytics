/**
 * @file index.ts
 * @module stores/chat
 *
 * Main Zustand store definition for all chat-related state: the message list,
 * in-progress streaming buffers, busy/cancelled flags, session cache, and
 * server message handling.
 *
 * The store is split across focused modules:
 * - {@link ./types}            -- ChatState interface, CachedSessionState
 * - {@link ./streamingHelpers} -- finalizeText, finalizeThinking, finalizeAll
 * - {@link ./sessionCache}     -- session cache CRUD actions
 * - {@link ./messageHandlers}  -- handleServerMessage dispatch
 */

import { create } from 'zustand'
import type { ChatState } from './types'
import { generateId } from '../../lib/utils'
import { api } from '../../lib/api'
import { finalizeAll, registerSetState } from './streamingHelpers'
import { createSessionCacheActions } from './sessionCache'
import { createHandleServerMessage } from './messageHandlers'

export type { ChatState, CachedSessionState } from './types'

/** @internal Zustand store instance. Use the exported {@link useChatStore} hook. */
export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  streamingText: '',
  streamingThinking: '',
  isBusy: false,
  cancelled: false,
  currentRunId: null,
  activeAgent: null,
  toolActivity: null,
  aupError: null,
  replayMode: false,
  pendingAttachments: [],
  _sessionCache: new Map(),

  handleServerMessage: createHandleServerMessage(set, get),

  addUserMessage: (text) => {
    // Finalize any orphaned streaming content BEFORE clearing the buffers.
    // Without this, partially-streamed assistant text would be silently destroyed.
    finalizeAll(get())

    set((prev) => ({
      messages: [
        ...prev.messages,
        {
          id: generateId(),
          role: 'user',
          content: text,
          timestamp: Date.now(),
        },
      ],
      isBusy: true,
      currentRunId: null,
      streamingText: '',
      streamingThinking: '',
    }))
  },

  setBusy: (busy) => set({ isBusy: busy }),
  setCancelled: (cancelled) => set({ cancelled }),
  setReplayMode: (mode) => set({ replayMode: mode }),

  addAttachment: (attachment) =>
    set((s) => ({
      pendingAttachments: [...s.pendingAttachments, attachment],
    })),

  removeAttachment: (filePath) =>
    set((s) => ({
      pendingAttachments: s.pendingAttachments.filter(
        (att) => att.filePath !== filePath
      ),
    })),

  clearAttachments: () =>
    set({ pendingAttachments: [] }),

  ...createSessionCacheActions(set, get),

  clearMessages: () =>
    set({ messages: [], streamingText: '', streamingThinking: '', isBusy: false, cancelled: false, currentRunId: null, activeAgent: null, toolActivity: null, aupError: null, replayMode: false, pendingAttachments: [] }),

  loadHistory: async (sessionId, signal?, preserveBusy?) => {
    // When preserveBusy (reconnecting to a busy session), don't finalize
    // streaming content -- buffer replay events are rebuilding the streaming
    // buffers concurrently.
    if (!preserveBusy) {
      finalizeAll(get())
    }

    try {
      const { messages } = await api.getHistory(sessionId, signal)
      if (preserveBusy) {
        // Merge: load DB messages but preserve streaming buffers that
        // buffer replay events are concurrently rebuilding.
        set({
          messages,
          isBusy: get().isBusy,
          activeAgent: get().activeAgent,
          // streamingText / streamingThinking intentionally NOT touched
        })
        // Deduplicate: if streamingText matches an already-persisted
        // assistant message (from a completed block in the DB), clear
        // the streaming buffer to prevent duplicate finalization.
        const currentText = get().streamingText
        if (currentText) {
          const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
          if (lastAssistant && (lastAssistant.content === currentText || currentText.startsWith(lastAssistant.content))) {
            const overlap = lastAssistant.content === currentText
              ? ''
              : currentText.slice(lastAssistant.content.length)
            set({ streamingText: overlap })
          }
        }
        const currentThinking = get().streamingThinking
        if (currentThinking) {
          const lastThinking = [...messages].reverse().find(m => m.role === 'thinking')
          if (lastThinking && lastThinking.content === currentThinking) {
            set({ streamingThinking: '' })
          }
        }
      } else {
        set({
          messages,
          streamingText: '',
          streamingThinking: '',
          isBusy: false,
          activeAgent: null,
        })
      }
    } catch {
      // Session might not exist yet, or request was aborted
    }
  },
}))

// Register setState so streamingHelpers can flush buffers without a circular import.
registerSetState(useChatStore.setState.bind(useChatStore))
