import { useState, useCallback } from 'react'
import { Search, X, MessageSquare } from 'lucide-react'
import { api } from '../../lib/api'
import { useChatStore } from '../../stores/chat'
import { useSessionsStore } from '../../stores/sessions'
import type { SearchResult, ClientMessage } from '../../lib/types'

interface Props {
  send: (msg: ClientMessage) => void
  onClose: () => void
}

function formatTimestamp(ts: string): string {
  try {
    const date = new Date(ts)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    if (diffDays === 0) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

export function SearchPanel({ send, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const res = await api.searchConversations(query)
      setResults(res.results)
    } catch {
      setResults([])
    }
    setSearching(false)
  }, [query])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
    if (e.key === 'Escape') onClose()
  }

  const handleResultClick = async (sessionId: string) => {
    useSessionsStore.getState().setActiveSession(sessionId)
    await useChatStore.getState().loadHistory(sessionId)
    send({ type: 'switch_session', session_id: sessionId })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-md flex items-start justify-center pt-[15vh]"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full max-w-xl glass-strong rounded-2xl shadow-2xl overflow-hidden animate-scale-in">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border">
          <Search size={18} className="text-text-muted flex-shrink-0" />
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search conversations..."
            className="flex-1 bg-transparent text-text-primary text-sm outline-none placeholder:text-text-muted"
          />
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-2 text-text-muted">
            <X size={16} />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto">
          {searching && (
            <div className="text-center text-text-muted text-sm py-8">Searching...</div>
          )}
          {!searching && results.length === 0 && query && (
            <div className="text-center text-text-muted text-sm py-8">No results found</div>
          )}
          {!searching && results.length === 0 && !query && (
            <div className="text-center text-text-muted text-sm py-8">
              Type to search across all conversations
            </div>
          )}
          {results.map((result, i) => (
            <button
              key={`${result.session_id}-${i}`}
              onClick={() => handleResultClick(result.session_id)}
              className="w-full text-left px-4 py-3.5 hover:bg-surface-2 transition-colors border-b border-border last:border-0"
            >
              <div className="flex items-center gap-2 mb-1">
                <MessageSquare size={12} className="text-accent flex-shrink-0" />
                <span className="text-xs font-medium text-accent truncate">{result.session_title}</span>
                <span className="text-[11px] text-text-muted ml-auto flex-shrink-0">{formatTimestamp(result.timestamp)}</span>
              </div>
              <p className="text-sm text-text-primary line-clamp-2">{result.snippet}</p>
            </button>
          ))}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2.5 border-t border-border text-[11px] text-text-muted flex items-center gap-4">
          <span><kbd className="px-1.5 py-0.5 rounded-md glass text-text-muted font-mono">Enter</kbd> to search</span>
          <span><kbd className="px-1.5 py-0.5 rounded-md glass text-text-muted font-mono">Esc</kbd> to close</span>
        </div>
      </div>
    </div>
  )
}
