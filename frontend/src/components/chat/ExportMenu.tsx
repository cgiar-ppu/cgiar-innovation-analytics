import { useState, useRef, useEffect } from 'react'
import { Download, FileText, FileCode, File, ChevronDown } from 'lucide-react'
import { useSessionsStore } from '../../stores/sessions'
import { api } from '../../lib/api'

const FORMATS = [
  { key: 'docx', label: 'Word Document', desc: 'Best for editing & sharing', icon: FileText },
  { key: 'pdf', label: 'PDF', desc: 'Best for archival & printing', icon: File },
  { key: 'html', label: 'HTML Page', desc: 'View in any browser', icon: FileCode },
  { key: 'md', label: 'Markdown', desc: 'Plain text with formatting', icon: FileText },
]

export function ExportMenu() {
  const [open, setOpen] = useState(false)
  const [detailed, setDetailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const activeSessionId = useSessionsStore((s) => s.activeSessionId)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleExport = (format: string) => {
    if (!activeSessionId) return
    window.open(api.exportUrl(activeSessionId, format, detailed ? 'full' : 'standard'), '_blank')
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        disabled={!activeSessionId}
        className="flex items-center gap-1 p-2 rounded-xl hover:bg-surface-2 transition-colors text-text-muted hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed"
        title={activeSessionId ? 'Export conversation' : 'Start a conversation first'}
      >
        <Download size={16} />
        <ChevronDown size={10} />
      </button>

      {open && activeSessionId && (
        <div className="absolute right-0 top-full mt-2 w-72 glass-strong rounded-2xl shadow-xl z-50 overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-text-primary">Export Conversation</p>
            <p className="text-[10px] text-text-muted mt-0.5">Download in your preferred format</p>
          </div>

          <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
            <div>
              <span className="text-xs text-text-primary font-medium">Detailed export</span>
              <span className="block text-[10px] text-text-muted">Include thinking, tool inputs/outputs</span>
            </div>
            <button
              onClick={() => setDetailed(!detailed)}
              className={`relative w-9 h-5 rounded-full transition-colors ${detailed ? 'bg-accent' : 'bg-surface-3'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform shadow-sm ${detailed ? 'translate-x-4' : ''}`} />
            </button>
          </div>

          {FORMATS.map((fmt) => (
            <button
              key={fmt.key}
              onClick={() => handleExport(fmt.key)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-2 transition-colors text-left"
            >
              <fmt.icon size={16} className="text-accent flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="text-sm text-text-primary font-medium">{fmt.label}</span>
                <span className="block text-[10px] text-text-muted">{fmt.desc}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
