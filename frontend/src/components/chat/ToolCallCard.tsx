import { memo, useState, useEffect } from 'react'
import { Wrench, Check, AlertCircle, AlertTriangle, Loader2 } from 'lucide-react'
import type { ChatMessage } from '../../lib/types'
import { truncate } from '../../lib/utils'
import { Expandable } from '../common/Expandable'
import { DiffView, shouldShowDiff } from './DiffView'
import { renderPreWithFileLinks } from './FileDownloadLink'
import { InteractiveContent } from './InteractiveContent'

/** Duration (ms) after which a pending tool call is considered stalled. */
const STALLED_TIMEOUT = 60_000

interface Props {
  message: ChatMessage
  result?: ChatMessage
}

export const ToolCallCard = memo(function ToolCallCard({ message, result }: Props) {
  const pending = !result
  const isError = result?.isError

  const [stalled, setStalled] = useState(false)

  useEffect(() => {
    if (!pending) {
      setStalled(false)
      return
    }
    const timer = setTimeout(() => setStalled(true), STALLED_TIMEOUT)
    return () => clearTimeout(timer)
  }, [pending])

  const statusColor = pending && !stalled
    ? 'border-warning'
    : stalled
      ? 'border-warning'
      : isError
        ? 'border-danger'
        : 'border-success'

  const StatusIcon = pending && !stalled
    ? Loader2
    : stalled
      ? AlertTriangle
      : isError
        ? AlertCircle
        : Check

  const showDiff = shouldShowDiff(message.tool) && message.toolInput

  return (
    <Expandable
      defaultExpanded={!result}
      className={`animate-fade-in-up border-l-2 ${statusColor} glass rounded-xl overflow-hidden`}
      header={
        <>
          <Wrench size={14} className="text-text-muted flex-shrink-0" />
          <span className="font-medium">{message.tool}</span>
          <span title={stalled ? 'This tool call may have stalled' : undefined} className="flex-shrink-0 ml-auto">
            <StatusIcon
              size={14}
              className={
                pending && !stalled ? 'text-warning animate-spin' :
                stalled ? 'text-amber-500' :
                isError ? 'text-danger' : 'text-success'
              }
            />
          </span>
        </>
      }
    >
      <div className="px-3 pb-3 space-y-2">
        {/* Diff view for Edit/Write tools */}
        {showDiff && (
          <DiffView tool={message.tool!} toolInput={message.toolInput!} />
        )}

        {/* Standard input display for non-diff tools */}
        {!showDiff && message.toolInput && (
          <div>
            <span className="text-[11px] font-medium text-text-muted uppercase tracking-wider">Input</span>
            <pre className="text-xs bg-surface-3 rounded-lg p-2.5 mt-1 overflow-x-auto text-text-muted font-mono border border-border whitespace-pre-wrap break-words">
              {renderPreWithFileLinks(truncate(JSON.stringify(message.toolInput, null, 2), 500))}
            </pre>
          </div>
        )}

        {/* Output section */}
        {result && (
          <div>
            <span className="text-[11px] font-medium text-text-muted uppercase tracking-wider">Output</span>
            {result.content && (
              <InteractiveContent content={result.content} className="mb-2" />
            )}
            <pre className={`text-xs rounded-lg p-2.5 mt-1 overflow-x-auto font-mono border whitespace-pre-wrap break-words ${
              isError ? 'bg-danger-soft border-danger/20 text-danger' : 'bg-surface-3 border-border text-text-muted'
            }`}>
              {renderPreWithFileLinks(truncate(result.content, 500))}
            </pre>
          </div>
        )}
      </div>
    </Expandable>
  )
})
