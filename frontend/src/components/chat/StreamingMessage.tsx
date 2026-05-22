import { useState, useEffect, useRef, memo } from 'react'
import { Sparkles, Brain } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { ThinkingBlock } from './ThinkingBlock'
import { REMARK_PLUGINS, STREAMING_MD_COMPONENTS } from './markdownComponents'

interface Props {
  text: string
  thinking: string
  expandedView?: boolean
}

const THROTTLE_MS = 120
const CURSOR_LINGER_MS = 500

const PROSE_CLASSES = `flex-1 min-w-0 overflow-hidden prose prose-sm md:prose-base dark:prose-invert max-w-none text-text-primary break-words
            prose-headings:text-text-primary prose-p:text-text-primary prose-li:text-text-primary
            prose-strong:text-text-primary prose-a:text-accent prose-code:text-accent
            prose-pre:bg-surface-3 prose-pre:border prose-pre:border-border prose-pre:rounded-xl
            prose-blockquote:border-accent prose-blockquote:text-text-muted
            prose-th:text-text-primary prose-td:text-text-primary
            prose-hr:border-border`

export const StreamingMessage = memo(function StreamingMessage({ text, thinking, expandedView = false }: Props) {
  // renderedText is the throttled value fed to ReactMarkdown
  const [renderedText, setRenderedText] = useState(text)
  // isStreaming drives the blinking cursor — true while tokens are arriving
  const [isStreaming, setIsStreaming] = useState(false)

  const latestTextRef = useRef(text)
  const throttleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cursorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    latestTextRef.current = text

    // --- cursor: mark as streaming, reset the linger timer ----
    setIsStreaming(true)
    if (cursorTimerRef.current) clearTimeout(cursorTimerRef.current)
    cursorTimerRef.current = setTimeout(() => {
      setIsStreaming(false)
    }, CURSOR_LINGER_MS)

    // --- throttle: update renderedText at most once per THROTTLE_MS ---
    if (!throttleTimerRef.current) {
      // No throttle window active — update immediately (leading edge)
      setRenderedText(text)
      throttleTimerRef.current = setTimeout(() => {
        throttleTimerRef.current = null
        // Flush any text that arrived during the throttle window (trailing edge)
        if (latestTextRef.current !== text) {
          setRenderedText(latestTextRef.current)
        }
      }, THROTTLE_MS)
    }
    // If a throttle window IS active, the timer callback will pick up
    // the latest value from latestTextRef when it fires.
  }, [text])

  // Cleanup all timers on unmount
  useEffect(() => {
    return () => {
      if (throttleTimerRef.current) clearTimeout(throttleTimerRef.current)
      if (cursorTimerRef.current) clearTimeout(cursorTimerRef.current)
    }
  }, [])

  if (!text && !thinking) return null

  return (
    <div className="space-y-4">
      {thinking && (
        expandedView ? (
          <ThinkingBlock content={thinking} isActive={true} />
        ) : (
          <div className="animate-fade-in-up flex items-center gap-2 px-3 py-2 glass rounded-xl text-xs text-text-muted">
            <Brain size={14} className="text-purple animate-thinking-pulse" />
            <span className="font-medium">Thinking...</span>
          </div>
        )
      )}
      {text && (
        <div className="flex gap-3">
          <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] flex items-center justify-center mt-0.5 shadow-sm">
            <Sparkles size={14} className="text-white" />
          </div>
          <div className={PROSE_CLASSES}>
            <ReactMarkdown
              remarkPlugins={REMARK_PLUGINS}
              components={STREAMING_MD_COMPONENTS}
            >
              {renderedText}
            </ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-accent rounded-sm animate-pulse ml-0.5 align-text-bottom" />
            )}
          </div>
        </div>
      )}
    </div>
  )
})
