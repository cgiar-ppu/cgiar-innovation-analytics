/**
 * @file InteractiveContent.tsx
 *
 * Wrapper that tries to render rich interactive content (charts, HTML dashboards)
 * from message text. Returns null when nothing interactive is detected, so the
 * parent falls back to regular text rendering with zero impact.
 */

import { useState, useMemo, Component, type ReactNode, type ErrorInfo } from 'react'
import { Globe, ChevronDown, ChevronUp, Code2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { detectCharts, type ChartData } from './chartDetector'
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

/**
 * Model- or tool-produced HTML runs in an OPAQUE-origin sandbox (L4-01/L1-05):
 * `allow-scripts` only, never `allow-same-origin`, so its script cannot read
 * the app's storage (login token) or call the API as the user. The former
 * "Open in new tab" (a same-origin blob: URL, i.e. full app privileges) is
 * gone; downloadable dashboards come from the Files area instead.
 */
export const HTML_SANDBOX = 'allow-scripts'

function HtmlDashboard({ content }: { content: string }) {
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
      </div>
      <iframe
        srcDoc={content}
        sandbox={HTML_SANDBOX}
        referrerPolicy="no-referrer"
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

/** One chart plus its "Show raw data" toggle. */
function ChartWithRaw({ chartData }: { chartData: ChartData }) {
  const [showRaw, setShowRaw] = useState(false)
  return (
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
  )
}

export function InteractiveContent({ content, className = '' }: InteractiveContentProps) {
  // Memoize detection so we don't re-parse on every render. Every explicit
  // <chart> block renders (the parent strips their JSON from the text body).
  const charts = useMemo(() => detectCharts(content), [content])
  const isHtml = useMemo(() => isHtmlDocument(content), [content])

  // Nothing interactive detected — return null so parent renders normally
  if (charts.length === 0 && !isHtml) return null

  return (
    <ChartErrorBoundary>
      <div className={className}>
        {/* HTML dashboard */}
        {isHtml && <HtmlDashboard content={content} />}

        {/* Charts */}
        {charts.map((chartData, i) => (
          <ChartWithRaw key={i} chartData={chartData} />
        ))}
      </div>
    </ChartErrorBoundary>
  )
}
