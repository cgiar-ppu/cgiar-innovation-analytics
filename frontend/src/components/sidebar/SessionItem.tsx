import { useState, useRef, useEffect } from 'react'
import { Trash2, MessageSquare, Pin, PinOff } from 'lucide-react'
import type { Session } from '../../lib/types'
import { formatTimestamp, truncate } from '../../lib/utils'
import { useSessionsStore } from '../../stores/sessions'
import { api } from '../../lib/api'

interface Props {
  session: Session
  isActive: boolean
  onSelect: () => void
  onRename: (title: string) => void
  onDelete: () => void
}

export function SessionItem({ session, isActive, onSelect, onRename, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(session.title)
  const inputRef = useRef<HTMLInputElement>(null)
  const isBusy = useSessionsStore((s) => s.busySessions.has(session.session_id))

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const commitRename = () => {
    setEditing(false)
    const trimmed = editValue.trim()
    if (trimmed && trimmed !== session.title) {
      onRename(trimmed)
    } else {
      setEditValue(session.title)
    }
  }

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirm('Delete this session?')) onDelete()
  }

  const handleTogglePin = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.pinSession(session.session_id, !session.pinned)
      useSessionsStore.getState().loadSessions()
    } catch (err) {
      console.error('Failed to toggle pin:', err)
    }
  }

  return (
    <div
      onClick={onSelect}
      onDoubleClick={() => setEditing(true)}
      className={`group flex items-start gap-2.5 px-3 py-2.5 cursor-pointer transition-all rounded-xl my-0.5
        ${isActive
          ? 'glass border border-accent/20'
          : 'hover:bg-surface-2 border border-transparent'
        }`}
    >
      <div className="relative mt-0.5 flex-shrink-0">
        {session.pinned ? (
          <Pin size={14} className="text-accent" />
        ) : (
          <MessageSquare size={14} className={isBusy ? 'text-accent' : 'text-text-muted'} />
        )}
        {isBusy && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-accent rounded-full animate-pulse" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') { setEditing(false); setEditValue(session.title) }
            }}
            className="w-full bg-surface-3 text-text-primary text-sm px-2 py-1 rounded-lg border border-border outline-none focus:border-accent"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <div className="text-sm text-text-primary truncate">
            {truncate(session.title, 60)}
          </div>
        )}
        <div className="flex items-center gap-2 text-[11px] text-text-muted mt-0.5">
          <span>{formatTimestamp(session.updated_at)}</span>
          <span>{session.message_count} msg{session.message_count !== 1 ? 's' : ''}</span>
        </div>
      </div>
      <div className="flex items-center gap-0.5 flex-shrink-0">
        <button
          onClick={handleTogglePin}
          className={`p-1 rounded-lg hover:bg-surface-2 text-text-muted hover:text-accent
            transition-all flex-shrink-0 ${session.pinned ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
          aria-label={session.pinned ? 'Unpin session' : 'Pin session'}
          title={session.pinned ? 'Unpin session' : 'Pin session'}
        >
          {session.pinned ? <PinOff size={14} /> : <Pin size={14} />}
        </button>
        <button
          onClick={handleDelete}
          className="p-1 rounded-lg hover:bg-danger-soft text-text-muted hover:text-danger
            opacity-0 group-hover:opacity-100 transition-all flex-shrink-0"
          aria-label="Delete session"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}
