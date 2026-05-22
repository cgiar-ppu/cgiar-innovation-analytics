import { MessageSquare, FolderOpen, Brain, X } from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import { SessionList } from '../sidebar/SessionList'
import { FileList } from '../sidebar/FileList'
import { MemoryList } from '../sidebar/MemoryList'
import type { ClientMessage } from '../../lib/types'

interface SidebarProps {
  send: (msg: ClientMessage) => void
}

const tabs = [
  { id: 'sessions' as const, label: 'Sessions', icon: MessageSquare },
  { id: 'files' as const, label: 'Files', icon: FolderOpen },
  { id: 'memory' as const, label: 'Memory', icon: Brain },
]

export function Sidebar({ send }: SidebarProps) {
  const { sidebarOpen, sidebarTab, setSidebarTab, setSidebarOpen } = useUIStore()

  if (!sidebarOpen) return null

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className="fixed inset-0 bg-black/30 backdrop-blur-md z-20 md:hidden"
        onClick={() => setSidebarOpen(false)}
      />

      <aside className="w-sidebar flex-shrink-0 flex flex-col h-full
        fixed md:relative z-30 md:z-auto top-0 left-0 bottom-0
        bg-sidebar-bg backdrop-blur-xl border-r border-border">
        {/* Mobile close button */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="absolute top-3 right-3 p-1.5 rounded-xl hover:bg-surface-2 transition-colors md:hidden text-text-muted"
        >
          <X size={16} />
        </button>

        {/* Tabs */}
        <div className="flex border-b border-border">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSidebarTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-3 text-xs font-medium transition-all relative
                ${sidebarTab === tab.id
                  ? 'text-accent'
                  : 'text-text-muted hover:text-text-primary'
                }`}
            >
              <tab.icon size={14} />
              <span>{tab.label}</span>
              {sidebarTab === tab.id && (
                <span className="absolute bottom-0 left-1/4 right-1/4 h-0.5 bg-accent rounded-full" />
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto">
          {sidebarTab === 'sessions' && <SessionList send={send} />}
          {sidebarTab === 'files' && <FileList />}
          {sidebarTab === 'memory' && <MemoryList />}
        </div>
      </aside>
    </>
  )
}
