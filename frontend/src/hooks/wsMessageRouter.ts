/**
 * @file wsMessageRouter.ts
 * @module hooks
 *
 * Extracted message routing logic for the WebSocket hook. Handles all
 * incoming {@link ServerMessage} variants by dispatching to the
 * appropriate Zustand store actions.
 *
 * Separated from `useWebSocket.ts` to keep the hook focused on
 * connection management while this module owns message interpretation.
 */

import type { ServerMessage } from '../lib/types'
import { useChatStore } from '../stores/chat'
import { useSessionsStore } from '../stores/sessions'

/**
 * Context passed to the router so it can access connection-scoped state
 * without reaching into React refs.
 */
export interface RouterContext {
  /** Returns the session_id of the last processed session_complete (dedup guard). */
  getLastSessionComplete: () => { sessionId: string; timestamp: number } | null
  /** Updates the last processed session_complete record. */
  setLastSessionComplete: (record: { sessionId: string; timestamp: number }) => void
}

/**
 * Routes a parsed WebSocket message to the appropriate store actions.
 *
 * @returns `true` if the message was handled, `false` if it was unrecognized
 *          (caller should log a warning).
 */
export function routeWebSocketMessage(
  msg: ServerMessage & { session_id?: string },
  ctx: RouterContext,
): boolean {
  const activeSession = useSessionsStore.getState().activeSessionId
  const msgSession = (msg as { session_id?: string }).session_id

  // ---- Session management: always process regardless of session_id ----

  if (msg.type === 'session') {
    handleSessionMessage(msg)
    return true
  }

  if (msg.type === 'sessions_changed') {
    useSessionsStore.getState().loadSessions()
    return true
  }

  if (msg.type === 'session_update') {
    handleSessionUpdate(msg)
    return true
  }

  if (msg.type === 'session_complete') {
    handleSessionComplete(msg, ctx)
    return true
  }

  // ---- Buffer replay markers ----

  if (msg.type === 'buffer_replay_start') {
    handleBufferReplayStart(msg)
    return true
  }

  if (msg.type === 'buffer_replay_end') {
    handleBufferReplayEnd(msg)
    return true
  }

  // ---- Active session messages ----

  if (!msgSession || (activeSession && msgSession === activeSession)) {
    // Reject stale events from previous turns via run_id filtering
    const chatState = useChatStore.getState()
    const msgRunId = (msg as { run_id?: string }).run_id
    if (msgRunId && chatState.currentRunId && msgRunId !== chatState.currentRunId) {
      console.debug('[WebSocket] Ignoring stale event from run', msgRunId, 'current:', chatState.currentRunId)
      return true
    }
    chatState.handleServerMessage(msg as ServerMessage)
    if (msg.type === 'result' || msg.type === 'cancelled' || msg.type === 'error') {
      useSessionsStore.getState().markSessionComplete(msgSession || activeSession || '')
    }
    return true
  }

  // ---- Background session messages ----

  return routeBackgroundMessage(msg, msgSession!)
}

// ---- Internal handlers ----

function handleSessionMessage(
  msg: Extract<ServerMessage, { type: 'session' }>,
): void {
  const wasBusy = useSessionsStore.getState().busySessions.has(msg.session_id)
  useSessionsStore.getState().setActiveSession(msg.session_id)
  useSessionsStore.getState().loadSessions()

  if (msg.is_busy) {
    useSessionsStore.getState().markSessionBusy(msg.session_id)
    useChatStore.getState().setBusy(true)
  } else if (msg.is_busy === false) {
    useChatStore.getState().setBusy(false)
    useSessionsStore.getState().markSessionComplete(msg.session_id)

    if (wasBusy && msg.session_id === useSessionsStore.getState().activeSessionId) {
      useChatStore.getState().invalidateCachedSession(msg.session_id)
      useChatStore.getState().loadHistory(msg.session_id)
    }
  }

  useChatStore.getState().handleServerMessage(msg as ServerMessage)
}

function handleSessionUpdate(
  msg: Extract<ServerMessage, { type: 'session_update' }>,
): void {
  if (msg.action === 'deleted') {
    const activeSession = useSessionsStore.getState().activeSessionId
    if (msg.session_id === activeSession) {
      useChatStore.getState().clearMessages()
      useSessionsStore.getState().setActiveSession(null)
    }
  }
  useSessionsStore.getState().loadSessions()
}

function handleSessionComplete(
  msg: Extract<ServerMessage, { type: 'session_complete' }> & { run_id?: string },
  ctx: RouterContext,
): void {
  // Run-id guard: reject stale session_complete from previous turns
  const chatState = useChatStore.getState()
  if (msg.run_id && chatState.currentRunId && msg.run_id !== chatState.currentRunId) {
    console.debug('[WebSocket] Ignoring stale session_complete from run', msg.run_id, 'current:', chatState.currentRunId)
    return
  }

  // Dedup guard: ignore duplicate session_complete for the same session
  // within a short window.
  const now = Date.now()
  const last = ctx.getLastSessionComplete()
  if (last && last.sessionId === msg.session_id && now - last.timestamp < 2000) {
    console.debug('[WebSocket] Ignoring duplicate session_complete for', msg.session_id)
    return
  }
  ctx.setLastSessionComplete({ sessionId: msg.session_id, timestamp: now })

  useSessionsStore.getState().markSessionComplete(msg.session_id)
  useSessionsStore.getState().loadSessions()

  const currentActive = useSessionsStore.getState().activeSessionId
  if (msg.session_id === currentActive) {
    const chatState = useChatStore.getState()
    const isActivelyStreaming = chatState.streamingText !== '' || chatState.streamingThinking !== ''
    if (isActivelyStreaming) {
      console.debug('[WebSocket] Ignoring stale session_complete — new turn is streaming')
    } else {
      chatState.handleServerMessage(msg as ServerMessage)
    }
  } else {
    useChatStore.getState().invalidateCachedSession(msg.session_id)
  }
}

function handleBufferReplayStart(
  msg: Extract<ServerMessage, { type: 'buffer_replay_start' }>,
): void {
  const currentActive = useSessionsStore.getState().activeSessionId
  if (msg.session_id === currentActive) {
    useChatStore.setState({ streamingText: '', streamingThinking: '' })
    useChatStore.getState().setReplayMode(true)
    useChatStore.getState().setBusy(true)
    useChatStore.getState().loadHistory(msg.session_id, undefined, true)
  }
}

function handleBufferReplayEnd(
  msg: Extract<ServerMessage, { type: 'buffer_replay_end' }>,
): void {
  const currentActive = useSessionsStore.getState().activeSessionId
  if (msg.session_id === currentActive) {
    useChatStore.getState().setReplayMode(false)
  }
}

/**
 * Routes messages belonging to a background (non-active) session.
 * Streaming deltas are cached; structural events invalidate the cache.
 */
function routeBackgroundMessage(
  msg: ServerMessage,
  msgSession: string,
): boolean {
  if (msg.type === 'text') {
    useChatStore.getState().appendToCachedStream(msgSession, 'streamingText', msg.content)
    return true
  }
  if (msg.type === 'thinking') {
    useChatStore.getState().appendToCachedStream(msgSession, 'streamingThinking', msg.content)
    return true
  }
  if (msg.type === 'system') {
    useChatStore.getState().invalidateCachedSession(msgSession)
    return true
  }
  if (msg.type === 'agent_activity') {
    return true // no-op for background sessions
  }
  if (msg.type === 'tool_use' || msg.type === 'tool_result') {
    useChatStore.getState().invalidateCachedSession(msgSession)
    return true
  }
  if (msg.type === 'result' || msg.type === 'cancelled' || msg.type === 'error') {
    useChatStore.getState().invalidateCachedSession(msgSession)
    useSessionsStore.getState().markSessionComplete(msgSession)
    useSessionsStore.getState().loadSessions()
    return true
  }

  return true
}
