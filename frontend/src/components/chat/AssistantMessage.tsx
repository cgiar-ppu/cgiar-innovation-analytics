import { memo } from 'react'
import { Copy, Check, Sparkles } from 'lucide-react'
import { TTSSpeakButton } from './TTSSpeakButton'
import ReactMarkdown from 'react-markdown'
import type { ChatMessage } from '../../lib/types'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'
import { InteractiveContent } from './InteractiveContent'
import { REMARK_PLUGINS, ASSISTANT_MD_COMPONENTS } from './markdownComponents'

interface Props {
  message: ChatMessage
}

export const AssistantMessage = memo(function AssistantMessage({ message }: Props) {
  const { copied, copyToClipboard } = useCopyToClipboard()

  return (
    <div className="flex gap-3 animate-fade-in-up group">
      <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] flex items-center justify-center mt-0.5 shadow-sm">
        <Sparkles size={14} className="text-white" />
      </div>
      <div className="flex-1 min-w-0 overflow-hidden relative">
        <InteractiveContent content={message.content} />
        <div className="prose prose-sm md:prose-base dark:prose-invert max-w-none text-text-primary break-words
          prose-headings:text-text-primary prose-p:text-text-primary prose-li:text-text-primary
          prose-strong:text-text-primary prose-a:text-accent prose-code:text-accent
          prose-pre:bg-surface-3 prose-pre:border prose-pre:border-border prose-pre:rounded-xl
          prose-blockquote:border-accent prose-blockquote:text-text-muted
          prose-th:text-text-primary prose-td:text-text-primary
          prose-hr:border-border">
          <ReactMarkdown
            remarkPlugins={REMARK_PLUGINS}
            components={ASSISTANT_MD_COMPONENTS}
          >
            {message.content}
          </ReactMarkdown>
        </div>
        <div className="absolute top-0 right-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
          <TTSSpeakButton messageId={message.id} text={message.content} />
          <button
            onClick={() => copyToClipboard(message.content)}
            className="p-1.5 rounded-lg glass text-text-muted hover:text-text-primary"
            aria-label="Copy message"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
      </div>
    </div>
  )
})
