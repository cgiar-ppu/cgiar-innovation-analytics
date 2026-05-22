import { memo } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, useMemo } from 'react'
import type { ChatMessage } from '../../lib/types'

interface Props {
  message: ChatMessage
}

const INLINE_LIMIT = 120

function pillLabel(msg: ChatMessage): string {
  if (msg.subtype === 'init') return 'Session Started'
  if (msg.subtype) return msg.subtype
  return 'System'
}

/** Try to render a compact init summary instead of raw JSON. */
function formatInitContent(raw: string): string | null {
  try {
    const data = JSON.parse(raw)
    if (!data.model) return null // Not a compact init summary

    const lines: string[] = []
    lines.push(`Model: ${data.model}`)
    if (typeof data.tools === 'number') {
      lines.push(`Tools: ${data.tools} available`)
    }
    if (Array.isArray(data.mcp_servers) && data.mcp_servers.length > 0) {
      const connected = data.mcp_servers.filter((s: { status: string }) => s.status === 'connected')
      lines.push(`MCP servers: ${connected.length}/${data.mcp_servers.length} connected`)
    }
    if (Array.isArray(data.slash_commands) && data.slash_commands.length > 0) {
      lines.push(`Commands: /${data.slash_commands.join(', /')}`)
    }
    if (Array.isArray(data.skills) && data.skills.length > 0) {
      lines.push(`Skills: ${data.skills.join(', ')}`)
    }
    if (Array.isArray(data.agents) && data.agents.length > 0) {
      lines.push(`Agents: ${data.agents.length} available`)
    }
    return lines.join('\n')
  } catch {
    return null
  }
}

export const SystemMessage = memo(function SystemMessage({ message }: Props) {
  const content = message.content ?? ''
  const [expanded, setExpanded] = useState(false)

  // For init messages, try to show a formatted summary
  const formattedInit = useMemo(
    () => message.subtype === 'init' ? formatInitContent(content) : null,
    [content, message.subtype]
  )
  const displayContent = formattedInit ?? content
  const isLong = displayContent.length > INLINE_LIMIT

  if (!isLong) {
    return (
      <div className="flex justify-center animate-fade-in-up">
        <span className="text-xs text-text-muted glass px-3 py-1 rounded-full">
          {displayContent}
        </span>
      </div>
    )
  }

  const label = pillLabel(message)

  return (
    <div className="flex justify-center animate-fade-in-up">
      <div className="inline-flex flex-col items-center">
        <button
          onClick={() => setExpanded(!expanded)}
          className="inline-flex items-center gap-1.5 text-xs text-text-muted glass hover:border-border-hover px-3 py-1 rounded-full transition-colors cursor-pointer"
        >
          {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          <span>{label}</span>
        </button>

        <div
          className="grid transition-[grid-template-rows] duration-200 w-full"
          style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
        >
          <div className="overflow-hidden">
            <div className="mt-2 glass rounded-xl px-3 py-2 max-w-[min(32rem,calc(100vw-3rem))]">
              <pre className="text-xs text-text-muted whitespace-pre-wrap break-words font-mono leading-relaxed max-h-60 overflow-y-auto">
                {displayContent}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
})
