import { X, Maximize2, Minimize2 } from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import { useState } from 'react'
import type { AppConfig } from '../../lib/types'

interface Props {
  config: AppConfig | null
}

export function DesktopViewer({ config }: Props) {
  const { desktopPanelOpen, setDesktopPanelOpen } = useUIStore()
  const [isMaximized, setIsMaximized] = useState(false)

  if (!desktopPanelOpen || !config?.vnc_available) return null

  const vncPort = config.vnc_port || 6080
  const host = window.location.hostname
  const vncUrl = `/vnc/vnc.html?host=${host}&port=${vncPort}&autoconnect=true&resize=scale&reconnect=true&reconnect_delay=2000&path=websockify`

  return (
    <div className={`flex flex-col border-l border-border glass ${
      isMaximized ? 'fixed inset-0 z-50' : 'w-[50%] min-w-[400px]'
    }`}>
      <div className="flex items-center justify-between px-4 h-10 bg-surface-2 border-b border-border flex-shrink-0">
        <span className="text-xs font-medium text-text-muted">Desktop (noVNC)</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setIsMaximized(!isMaximized)}
            className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-muted"
            title={isMaximized ? 'Restore' : 'Maximize'}
          >
            {isMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button
            onClick={() => { setDesktopPanelOpen(false); setIsMaximized(false) }}
            className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-muted"
            title="Close desktop panel"
          >
            <X size={14} />
          </button>
        </div>
      </div>
      <iframe
        src={vncUrl}
        className="flex-1 w-full bg-black"
        title="Desktop viewer"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  )
}
