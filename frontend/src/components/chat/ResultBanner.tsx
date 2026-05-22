import { memo } from 'react'
import type { ChatMessage } from '../../lib/types'
import { formatCost, formatDuration } from '../../lib/utils'

interface Props {
  message: ChatMessage
}

export const ResultBanner = memo(function ResultBanner({ message }: Props) {
  if (message.isError) {
    return (
      <div className="flex justify-center animate-fade-in-up">
        <div className="flex flex-col items-center gap-1.5 text-xs glass rounded-2xl px-5 py-3 max-w-lg border border-danger/20">
          <div className="flex items-center gap-2 text-danger font-medium">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <span>Session ended with error</span>
          </div>
          {message.content && (
            <span className="text-text-muted text-center">{message.content}</span>
          )}
          <div className="flex items-center gap-3 text-text-muted mt-0.5">
            <span>{formatCost(message.estimatedCost, message.authMethod)}</span>
            <span className="w-px h-3 bg-border" />
            <span>{message.turns} turn{message.turns !== 1 ? 's' : ''}</span>
            <span className="w-px h-3 bg-border" />
            <span>{formatDuration(message.durationMs ?? 0)}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-center animate-fade-in-up">
      <div className="flex items-center gap-3 text-xs text-text-muted glass px-4 py-2 rounded-full flex-wrap max-w-full">
        <span>{formatCost(message.estimatedCost, message.authMethod)}</span>
        <span className="w-px h-3 bg-border" />
        <span>{message.turns} turn{message.turns !== 1 ? 's' : ''}</span>
        <span className="w-px h-3 bg-border" />
        <span>{formatDuration(message.durationMs ?? 0)}</span>
      </div>
    </div>
  )
})
