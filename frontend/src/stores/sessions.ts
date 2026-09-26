/**
 * @file sessions.ts
 * @module stores
 *
 * Zustand store for chat session management: the list of past sessions, the
 * currently active session ID, and async actions that call the REST API to
 * load, rename, or delete sessions.
 *
 * The active session drives which history is loaded in the chat store and which
 * WebSocket session the server streams events into.
 */

import { create } from 'zustand'
import type { Session } from '../lib/types'
import { api } from '../lib/api'
import { ACTIVE_SESSION_KEY, onUserStateReset } from './userStateReset'

/**
 * Shape of the sessions Zustand store.
 * Combines reactive state fields with async action methods.
 */
interface SessionsState {
  /** All sessions belonging to the current user, ordered by recency. */
  sessions: Session[]

  /**
   * The `session_id` of the session the user is currently viewing.
   * `null` before the first session is created or selected.
   */
  activeSessionId: string | null

  /** `true` while {@link loadSessions} is in flight. */
  loading: boolean

  /** Set of session IDs that currently have in-flight agent tasks. */
  busySessions: Set<string>

  /**
   * Fetches the full session list from the API and replaces {@link sessions}.
   * Sets {@link loading} to `true` before the request and `false` on
   * completion (success or error).
   */
  loadSessions: () => Promise<void>

  /**
   * Updates {@link activeSessionId} without triggering a network request.
   * The WebSocket hook and chat store observe this value to load history and
   * route incoming messages.
   *
   * @param id - The session to make active, or `null` to deselect all.
   */
  setActiveSession: (id: string | null) => void

  /** Mark a session as having an in-flight task. */
  markSessionBusy: (id: string) => void

  /** Mark a session as no longer having an in-flight task. */
  markSessionComplete: (id: string) => void

  /**
   * Optimistically update the model for a session in the local list.
   * Called when the user picks a different model in the selector pill (the
   * backend confirms via a `model_switched` WebSocket frame).
   *
   * @param id    - The `session_id` whose model changed.
   * @param model - The new model ID.
   */
  setSessionModel: (id: string, model: string) => void

  /**
   * Optimistic model switch awaiting the server's `model_switched` (L4-10):
   * the previous model is kept so the pill can roll back when the send fails
   * or the server answers `model_not_allowed`.
   */
  pendingModelSwitch: { sessionId: string; previous: string | undefined; model: string } | null

  /** Record an optimistic switch and update the pill label. */
  beginModelSwitch: (id: string, model: string) => void

  /** The server confirmed the switch. */
  confirmModelSwitch: (id: string, model: string) => void

  /** Undo the optimistic switch (send failed or the server refused it). */
  rollbackModelSwitch: () => void

  /**
   * Sends a PATCH request to rename a session and optimistically updates the
   * local {@link sessions} list.
   *
   * @param id    - The `session_id` of the session to rename.
   * @param title - The new display title.
   */
  renameSession: (id: string, title: string) => Promise<void>

  /**
   * Sends a DELETE request to remove a session and removes it from the local
   * {@link sessions} list.
   *
   * @param id - The `session_id` of the session to delete.
   */
  deleteSession: (id: string) => Promise<void>
}

/** @internal Zustand store instance. Use the exported {@link useSessionsStore} hook. */
export const useSessionsStore = create<SessionsState>((set, get) => ({
  sessions: [],
  activeSessionId: (() => {
    try {
      return localStorage.getItem(ACTIVE_SESSION_KEY) || null
    } catch {
      return null
    }
  })(),
  loading: false,
  busySessions: new Set<string>(),
  pendingModelSwitch: null,

  loadSessions: async () => {
    set({ loading: true })
    try {
      // Empty chats are hidden server-side (QA-4 D12); keep the active one.
      const { sessions } = await api.getSessions(get().activeSessionId)
      set({ sessions, loading: false })
    } catch {
      set({ loading: false })
    }
  },

  setActiveSession: (id) => {
    set({ activeSessionId: id })
    // Persist to localStorage so it survives page refreshes
    try {
      if (id) {
        localStorage.setItem(ACTIVE_SESSION_KEY, id)
      } else {
        localStorage.removeItem(ACTIVE_SESSION_KEY)
      }
    } catch {
      // localStorage may be unavailable (private browsing, etc.)
    }
  },

  markSessionBusy: (id) => set((s) => {
    const next = new Set(s.busySessions)
    next.add(id)
    return { busySessions: next }
  }),

  markSessionComplete: (id) => set((s) => {
    const next = new Set(s.busySessions)
    next.delete(id)
    return { busySessions: next }
  }),

  setSessionModel: (id, model) => set((s) => ({
    sessions: s.sessions.map((sess) =>
      sess.session_id === id ? { ...sess, model } : sess,
    ),
  })),

  beginModelSwitch: (id, model) => {
    const previous = get().sessions.find((sess) => sess.session_id === id)?.model
    set({ pendingModelSwitch: { sessionId: id, previous, model } })
    get().setSessionModel(id, model)
  },

  confirmModelSwitch: (id, model) => {
    get().setSessionModel(id, model)
    const pending = get().pendingModelSwitch
    if (pending && pending.sessionId === id) set({ pendingModelSwitch: null })
  },

  rollbackModelSwitch: () => {
    const pending = get().pendingModelSwitch
    if (!pending) return
    set((s) => ({
      pendingModelSwitch: null,
      sessions: s.sessions.map((sess) =>
        sess.session_id === pending.sessionId ? { ...sess, model: pending.previous ?? '' } : sess,
      ),
    }))
  },

  renameSession: async (id, title) => {
    await api.renameSession(id, title)
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.session_id === id ? { ...sess, title } : sess,
      ),
    }))
  },

  deleteSession: async (id) => {
    await api.deleteSession(id)
    const state = get()
    set({
      sessions: state.sessions.filter((s) => s.session_id !== id),
    })
  },
}))

// L4-04: the session list and the open chat belong to one user only.
onUserStateReset(() => {
  useSessionsStore.setState({ sessions: [], activeSessionId: null, loading: false, busySessions: new Set<string>(), pendingModelSwitch: null })
})
