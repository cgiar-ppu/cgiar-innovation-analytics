import { memo } from 'react'
import type { ChatMessage } from '../../lib/types'

interface Props {
  message: ChatMessage
}

export const UserMessage = memo(function UserMessage({ message }: Props) {
  return (
    <div className="flex justify-end animate-fade-in-up">
      <div
        className="max-w-[80%] md:max-w-[70%] px-4 py-3 rounded-2xl rounded-br-md text-sm leading-relaxed whitespace-pre-wrap break-words overflow-hidden shadow-sm"
        style={{
          background: 'var(--user-bubble)',
          color: 'var(--user-bubble-text)',
        }}
      >
        {message.content}
      </div>
    </div>
  )
})
