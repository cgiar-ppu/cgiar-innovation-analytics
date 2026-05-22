import { useRef } from 'react'
import { Plus } from 'lucide-react'
import { useSessionsStore } from '../../stores/sessions'
import { useChatStore } from '../../stores/chat'
import { SessionItem } from './SessionItem'
import type { ClientMessage } from '../../lib/types'


interface Props {
  send: (msg: ClientMessage) => void
}

export function SessionList({ send }: Props) {
  const { sessions, activeSessionId } = useSessionsStore()
  const { renameSession, deleteSession, setActiveSession, loadSessions } = useSessionsStore()
  const abortRef = useRef<AbortController | null>(null)

  const handleNewChat = () => {
    // Cache the streaming session before switching so background tokens
    // keep accumulating — same as handleSelect does for session switches.
    const currentSession = useSessionsStore.getState().activeSessionId
    if (currentSession) {
      useChatStore.getState().cacheCurrentSession(currentSession)
    }
    useChatStore.getState().clearMessages()
    setActiveSession(null)
    send({ type: 'new_session' })
  }

  const handleSelect = async (sessionId: string) => {
    if (sessionId === activeSessionId) return
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    // Cache the current session's state before switching away
    if (activeSessionId) {
      useChatStore.getState().cacheCurrentSession(activeSessionId)
    }

    setActiveSession(sessionId)

    // If the session was previously marked busy, its cache may be stale:
    // when we detach from a session's event stream (by switching away),
    // completion events (result, session_complete) are buffered by the
    // ChatRunManager but never forwarded to this connection. The cache
    // therefore reflects the state at the time we left, not the current
    // state. Invalidate it so we always load fresh data from the DB.
    const wasBusy = useSessionsStore.getState().busySessions.has(sessionId)
    if (wasBusy) {
      useChatStore.getState().invalidateCachedSession(sessionId)
    }

    // Try to restore from cache first (preserves streaming state)
    const restored = useChatStore.getState().restoreSession(sessionId)

    if (!restored) {
      // No cache — load from server
      try {
        // For sessions that are (or were) busy, use preserveBusy so the
        // backend's buffer_replay_start can reconcile streaming state.
        await useChatStore.getState().loadHistory(sessionId, abortRef.current.signal, wasBusy)
      } catch { /* aborted or failed */ }
    }

    // Always tell the backend about the switch so subsequent messages are routed correctly
    send({ type: 'switch_session', session_id: sessionId })

    // Ensure busy state is set if the session is known to be busy
    if (useSessionsStore.getState().busySessions.has(sessionId)) {
      useChatStore.getState().setBusy(true)
    }
  }

  const handleDelete = async (sessionId: string) => {
    await deleteSession(sessionId)
    if (sessionId === activeSessionId) {
      handleNewChat()
    }
    await loadSessions()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-3">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-white text-sm font-medium
            shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all"
          style={{ background: 'var(--user-bubble)' }}
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2">
        {sessions.map((session) => (
          <SessionItem
            key={session.session_id}
            session={session}
            isActive={session.session_id === activeSessionId}
            onSelect={() => handleSelect(session.session_id)}
            onRename={(title) => renameSession(session.session_id, title)}
            onDelete={() => handleDelete(session.session_id)}
          />
        ))}
        {sessions.length === 0 && (
          <div className="text-center text-text-muted text-xs py-8">
            No sessions yet
          </div>
        )}
      </div>
    </div>
  )
}
