import { memo } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { ChatMessage } from '../../lib/types'


/**
 * An inline notice in the conversation: a server refusal or error the user
 * must read (e.g. "The usage budget for this test period has been used up").
 * Shown in both compact and expanded views; never collapsed into
 * "1 system message" (verification round, Oct 2026).
 */
export const NoticeMessage = memo(function NoticeMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-center animate-fade-in-up" data-testid="chat-notice">
      <div
        role="alert"
        className="flex items-start gap-2 glass border border-warning rounded-xl px-4 py-3 max-w-[min(40rem,calc(100vw-3rem))] text-sm text-text"
      >
        <AlertTriangle size={16} className="text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
        <p className="whitespace-pre-wrap break-words leading-relaxed">{message.content}</p>
      </div>
    </div>
  )
})
