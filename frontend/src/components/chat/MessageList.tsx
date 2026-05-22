import { memo, useMemo } from 'react'
import { Wrench, Brain, Info, Check, AlertCircle, Loader2 } from 'lucide-react'
import type { ChatMessage, MessageRole } from '../../lib/types'
import { UserMessage } from './UserMessage'
import { AssistantMessage } from './AssistantMessage'
import { SystemMessage } from './SystemMessage'
import { ToolCallCard } from './ToolCallCard'
import { ThinkingBlock } from './ThinkingBlock'
import { ResultBanner } from './ResultBanner'

interface Props {
  messages: ChatMessage[]
  expandedView?: boolean
}

/** Roles that get collapsed in compact mode */
const COLLAPSIBLE_ROLES: Set<MessageRole> = new Set(['tool_use', 'tool_result', 'thinking', 'system'])

/** A group of consecutive collapsible messages shown as a single compact row */
interface CollapsedGroup {
  type: 'collapsed_group'
  id: string
  messages: ChatMessage[]
  toolCount: number
  thinkingCount: number
  systemCount: number
  hasError: boolean
  hasPending: boolean
}

/** Either a normal message or a collapsed group */
type RenderItem =
  | { type: 'message'; message: ChatMessage }
  | CollapsedGroup

function buildCompactItems(messages: ChatMessage[]): RenderItem[] {
  const items: RenderItem[] = []
  let currentGroup: ChatMessage[] | null = null

  const flushGroup = () => {
    if (!currentGroup || currentGroup.length === 0) return
    const toolMsgs = currentGroup.filter(m => m.role === 'tool_use')
    const thinkingMsgs = currentGroup.filter(m => m.role === 'thinking')
    const systemMsgs = currentGroup.filter(m => m.role === 'system')
    const resultMsgs = currentGroup.filter(m => m.role === 'tool_result')
    const hasError = resultMsgs.some(m => m.isError)
    const hasPending = toolMsgs.some(t => !resultMsgs.some(r => r.toolUseId === t.toolUseId))

    items.push({
      type: 'collapsed_group',
      id: `group-${currentGroup[0]!.id}`,
      messages: currentGroup,
      toolCount: toolMsgs.length,
      thinkingCount: thinkingMsgs.length,
      systemCount: systemMsgs.length,
      hasError,
      hasPending,
    })
    currentGroup = null
  }

  for (const msg of messages) {
    if (COLLAPSIBLE_ROLES.has(msg.role)) {
      if (!currentGroup) currentGroup = []
      currentGroup.push(msg)
    } else {
      flushGroup()
      items.push({ type: 'message', message: msg })
    }
  }
  flushGroup()

  return items
}

const CollapsedGroupRow = memo(function CollapsedGroupRow({ group }: { group: CollapsedGroup }) {
  const parts: { icon: typeof Wrench; label: string; count: number; color: string }[] = []

  if (group.toolCount > 0) {
    parts.push({
      icon: Wrench,
      label: group.toolCount === 1 ? 'tool call' : 'tool calls',
      count: group.toolCount,
      color: group.hasError ? 'text-danger' : group.hasPending ? 'text-warning' : 'text-success',
    })
  }
  if (group.thinkingCount > 0) {
    parts.push({
      icon: Brain,
      label: group.thinkingCount === 1 ? 'thinking block' : 'thinking blocks',
      count: group.thinkingCount,
      color: 'text-purple',
    })
  }
  if (group.systemCount > 0) {
    parts.push({
      icon: Info,
      label: group.systemCount === 1 ? 'system message' : 'system messages',
      count: group.systemCount,
      color: 'text-text-muted',
    })
  }

  const StatusIcon = group.hasPending ? Loader2 : group.hasError ? AlertCircle : Check
  const statusColor = group.hasPending ? 'text-warning' : group.hasError ? 'text-danger' : 'text-success'

  return (
    <div className="animate-fade-in-up flex items-center gap-2 px-3 py-2 glass rounded-xl text-xs text-text-muted">
      {group.toolCount > 0 && (
        <span className={`flex-shrink-0 ${statusColor}`}>
          <StatusIcon size={14} className={group.hasPending ? 'animate-spin' : ''} />
        </span>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        {parts.map((part, i) => (
          <span key={i} className="flex items-center gap-1">
            <part.icon size={12} className={part.color} />
            <span className="font-medium">{part.count}</span>
            <span>{part.label}</span>
          </span>
        ))}
      </div>
    </div>
  )
}, (prev, next) =>
  prev.group.id === next.group.id &&
  prev.group.hasPending === next.group.hasPending &&
  prev.group.hasError === next.group.hasError &&
  prev.group.toolCount === next.group.toolCount &&
  prev.group.thinkingCount === next.group.thinkingCount &&
  prev.group.systemCount === next.group.systemCount
)

export const MessageList = memo(function MessageList({ messages, expandedView = false }: Props) {
  // Build a lookup for tool results by toolUseId
  const toolResults = useMemo(() => {
    const map = new Map<string, ChatMessage>()
    for (const msg of messages) {
      if (msg.role === 'tool_result' && msg.toolUseId) {
        map.set(msg.toolUseId, msg)
      }
    }
    return map
  }, [messages])

  // In compact mode, group consecutive collapsible messages
  const compactItems = useMemo(
    () => (expandedView ? null : buildCompactItems(messages)),
    [messages, expandedView]
  )

  // Expanded view — original rendering
  if (expandedView) {
    return (
      <>
        {messages.map((msg) => {
          switch (msg.role) {
            case 'user':
              return <UserMessage key={msg.id} message={msg} />
            case 'assistant':
              return <AssistantMessage key={msg.id} message={msg} />
            case 'system':
              return <SystemMessage key={msg.id} message={msg} />
            case 'tool_use':
              return (
                <ToolCallCard
                  key={msg.id}
                  message={msg}
                  result={msg.toolUseId ? toolResults.get(msg.toolUseId) : undefined}
                />
              )
            case 'tool_result':
              return null
            case 'thinking':
              return (
                <ThinkingBlock
                  key={msg.id}
                  content={msg.content}
                  isActive={msg.isActive ?? false}
                />
              )
            case 'result':
              return <ResultBanner key={msg.id} message={msg} />
            default:
              return null
          }
        })}
      </>
    )
  }

  // Compact view — grouped collapsible messages
  return (
    <>
      {compactItems!.map((item) => {
        if (item.type === 'collapsed_group') {
          return <CollapsedGroupRow key={item.id} group={item} />
        }
        const msg = item.message
        switch (msg.role) {
          case 'user':
            return <UserMessage key={msg.id} message={msg} />
          case 'assistant':
            return <AssistantMessage key={msg.id} message={msg} />
          case 'result':
            return <ResultBanner key={msg.id} message={msg} />
          default:
            return null
        }
      })}
    </>
  )
})
