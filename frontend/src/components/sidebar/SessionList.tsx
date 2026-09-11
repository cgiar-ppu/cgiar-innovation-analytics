import { Plus } from 'lucide-react'
import { useSessionsStore } from '../../stores/sessions'
import { newChat, openChat } from '../../lib/chatCommands'
import { SessionItem } from './SessionItem'
import type { ClientMessage } from '../../lib/types'


interface Props {
  send: (msg: ClientMessage) => void
}

export function SessionList({ send }: Props) {
  const { sessions, activeSessionId } = useSessionsStore()
  const { renameSession, deleteSession, loadSessions } = useSessionsStore()
  const handleNewChat = () => newChat(send)
  const handleSelect = (id: string) => { void openChat(id, send).catch(() => {}) }

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
