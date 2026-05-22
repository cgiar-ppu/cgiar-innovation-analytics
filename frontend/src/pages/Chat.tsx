import { useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { Sidebar } from '../components/layout/Sidebar'
import { ChatArea } from '../components/chat/ChatArea'
import { SearchPanel } from '../components/sidebar/SearchPanel'
import { useSessionsStore } from '../stores/sessions'
import { useChatStore } from '../stores/chat'
import { useUIStore } from '../stores/ui'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import { api } from '../lib/api'

export default function Chat() {
  const { searchOpen, setSearchOpen } = useUIStore()
  const { loadSessions } = useSessionsStore()

  const { send } = useWebSocketContext()

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // Cmd+K is handled globally by CommandPalette, which delegates to
  // toggleSearch() when on the /chat route. No local handler needed here.

  const handleUpload = useCallback(async (file: File) => {
    try {
      const result = await api.uploadFile(file)
      useChatStore.getState().addAttachment({
        fileName: file.name,
        filePath: result.path,
        fileSize: result.size,
      })
      toast.success(`Attached: ${file.name}`, {
        description: result.path,
        duration: 3000,
      })
    } catch (err) {
      console.error('Upload failed:', err)
      toast.error('Upload failed', {
        description: err instanceof Error ? err.message : 'Could not upload file',
        duration: 4000,
      })
    }
  }, [])

  return (
    <div className="flex flex-1 h-[calc(100dvh-3.5rem)] overflow-hidden">
      {/* Sidebar — requires send so it can switch/create sessions over WebSocket */}
      <Sidebar send={send} />

      <div className="flex-1 flex overflow-hidden">
        {/* ChatArea — send forwards messages; onFileUpload handles file attachments */}
        <ChatArea send={send} onFileUpload={handleUpload} />
      </div>

      {/* SearchPanel — overlays full screen; send is needed for session switching */}
      {searchOpen && (
        <SearchPanel send={send} onClose={() => setSearchOpen(false)} />
      )}
    </div>
  )
}
