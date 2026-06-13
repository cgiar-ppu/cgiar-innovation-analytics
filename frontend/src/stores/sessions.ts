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
      return localStorage.getItem('synapsis_active_session') || null
    } catch {
      return null
    }
  })(),
  loading: false,
  busySessions: new Set<string>(),

  loadSessions: async () => {
    set({ loading: true })
    try {
      const { sessions } = await api.getSessions()
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
        localStorage.setItem('synapsis_active_session', id)
      } else {
        localStorage.removeItem('synapsis_active_session')
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
