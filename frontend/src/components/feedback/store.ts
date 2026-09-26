/**
 * The signed-in user's own answer feedback, cached per chat so every answer
 * widget in a chat shares one GET /api/feedback call.
 */
import { create } from 'zustand'
import { useAuthStore } from '../../stores/auth'
import { FeedbackDisabledError, getOwnFeedback, type OwnFeedback } from './api'

interface FeedbackState {
  /** sessionId -> message_id (r1, r2, …) -> own feedback */
  bySession: Record<string, Record<string, OwnFeedback>>
  loaded: Record<string, boolean>
  /** Feedback switched off on the server (IA_FEEDBACK_ENABLED=false): widgets hide. */
  disabled: boolean
  load: (sessionId: string) => Promise<void>
  put: (sessionId: string, feedback: OwnFeedback) => void
  remove: (sessionId: string, messageId: string) => void
  reset: () => void
}

const inFlight = new Set<string>()

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  bySession: {},
  loaded: {},
  disabled: false,
  load: async sessionId => {
    if (get().loaded[sessionId] || inFlight.has(sessionId) || get().disabled) return
    inFlight.add(sessionId)
    try {
      const { feedback } = await getOwnFeedback(sessionId)
      const map: Record<string, OwnFeedback> = {}
      for (const row of feedback) map[row.message_id] = row
      set(s => ({ bySession: { ...s.bySession, [sessionId]: map }, loaded: { ...s.loaded, [sessionId]: true } }))
    } catch (error) {
      if (error instanceof FeedbackDisabledError) set({ disabled: true })
      // Other errors: leave the widget usable; the next save will report problems.
      else set(s => ({ loaded: { ...s.loaded, [sessionId]: true } }))
    } finally {
      inFlight.delete(sessionId)
    }
  },
  put: (sessionId, feedback) => set(s => ({
    bySession: { ...s.bySession, [sessionId]: { ...(s.bySession[sessionId] || {}), [feedback.message_id]: feedback } },
  })),
  remove: (sessionId, messageId) => set(s => {
    const next = { ...(s.bySession[sessionId] || {}) }
    delete next[messageId]
    return { bySession: { ...s.bySession, [sessionId]: next } }
  }),
  reset: () => { inFlight.clear(); set({ bySession: {}, loaded: {}, disabled: false }) },
}))

// A different sign-in (or logout) on the same tab never sees the previous user's ratings.
useAuthStore.subscribe((state, previous) => {
  if (state.user?.userId !== previous.user?.userId) useFeedbackStore.getState().reset()
})
