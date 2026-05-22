/**
 * @file InteractiveContent.tsx
 *
 * Wrapper that tries to render rich interactive content (charts, HTML dashboards)
 * from message text. Returns null when nothing interactive is detected, so the
 * parent falls back to regular text rendering with zero impact.
 */

import { useState, useMemo, useCallback, Component, type ReactNode, type ErrorInfo } from 'react'
import { Globe, ChevronDown, ChevronUp, Code2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { detectChartData } from './chartDetector'
import { InteractiveChart } from './InteractiveChart'

// ---------------------------------------------------------------------------
// Inline ErrorBoundary (lightweight, renders nothing on failure)
// ---------------------------------------------------------------------------

interface EBProps { children: ReactNode }
interface EBState { hasError: boolean }

class ChartErrorBoundary extends Component<EBProps, EBState> {
  constructor(props: EBProps) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError(): EBState {
    return { hasError: true }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn('[InteractiveContent] Chart rendering failed:', error, info)
  }
  render() {
    if (this.state.hasError) return null
    return this.props.children
  }
}

// ---------------------------------------------------------------------------
// HTML dashboard detection & renderer
// ---------------------------------------------------------------------------

function isHtmlDocument(content: string): boolean {
  const trimmed = content.trim()
  return trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')
}

function HtmlDashboard({ content }: { content: string }) {
  const openInNewTab = useCallback(() => {
    const blob = new Blob([content], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    // Clean up after a delay
    setTimeout(() => URL.revokeObjectURL(url), 5000)
  }, [content])

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl overflow-hidden border border-white/5 my-2"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--surface-2)]/50 text-xs text-[var(--text-muted)]">
        <Globe size={12} />
        <span className="flex-1">Interactive Dashboard</span>
        <button
          onClick={openInNewTab}
          className="hover:text-[var(--text)] transition-colors"
        >
          Open in new tab &#x2197;
        </button>
      </div>
      <iframe
        srcDoc={content}
        sandbox="allow-scripts allow-same-origin"
        className="w-full bg-white"
        style={{ height: 500 }}
        title="Interactive content"
      />
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface InteractiveContentProps {
  content: string
  className?: string
}

export function InteractiveContent({ content, className = '' }: InteractiveContentProps) {
  const [showRaw, setShowRaw] = useState(false)

  // Memoize detection so we don't re-parse on every render
  const chartData = useMemo(() => detectChartData(content), [content])
  const isHtml = useMemo(() => isHtmlDocument(content), [content])

  // Nothing interactive detected — return null so parent renders normally
  if (!chartData && !isHtml) return null

  return (
    <ChartErrorBoundary>
      <div className={className}>
        {/* HTML dashboard */}
        {isHtml && <HtmlDashboard content={content} />}

        {/* Chart */}
        {chartData && (
          <>
            <InteractiveChart data={chartData} className="my-2" />

            {/* Raw data toggle */}
            <button
              onClick={() => setShowRaw(prev => !prev)}
              className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors px-1 mt-1"
            >
              <Code2 size={11} />
              {showRaw ? 'Hide' : 'Show'} raw data
              {showRaw ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            <AnimatePresence>
              {showRaw && (
                <motion.pre
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="text-xs bg-[var(--surface-3)] rounded-lg p-2.5 mt-1 overflow-x-auto text-[var(--text-muted)] font-mono border border-[var(--border)] whitespace-pre-wrap break-words"
                >
                  {JSON.stringify(chartData.data, null, 2)}
                </motion.pre>
              )}
            </AnimatePresence>
          </>
        )}
      </div>
    </ChartErrorBoundary>
  )
}
